"""Chiamate al modello Claude: scelta delle parole + fotogrammi e verifica delle immagini."""
import base64
import json
import re
from pathlib import Path
from typing import Callable

import anthropic

from ..config import MODALITA_LOCALE, chiave_api, modello_claude
from .lyrics import parole_candidate


class ErroreAI(Exception):
    pass


def _client() -> anthropic.Anthropic:
    chiave = chiave_api()
    if not chiave:
        dove = "nella pagina Impostazioni" if MODALITA_LOCALE else "nel file .env (ANTHROPIC_API_KEY)"
        raise ErroreAI(f"Chiave API Anthropic non configurata: inseriscila {dove}.")
    return anthropic.Anthropic(api_key=chiave, max_retries=3, timeout=300.0)


def prova_chiave(chiave: str, modello: str) -> str:
    """Verifica chiave e modello con una richiesta minima. Restituisce un messaggio d'errore, vuoto se tutto ok."""
    try:
        client = anthropic.Anthropic(api_key=chiave.strip(), max_retries=1, timeout=30.0)
        client.messages.create(model=modello, max_tokens=5, messages=[{"role": "user", "content": "ciao"}])
    except anthropic.AuthenticationError:
        return "La chiave API non è valida."
    except anthropic.NotFoundError:
        return f"Il modello '{modello}' non esiste o non è disponibile per questa chiave."
    except anthropic.PermissionDeniedError:
        return "La chiave non ha il permesso di usare questo modello."
    except anthropic.APIStatusError as exc:
        return f"Errore dall'API Anthropic ({exc.status_code}): {exc.message}"
    except anthropic.APIConnectionError:
        return "Impossibile contattare l'API Anthropic: controlla la connessione a internet."
    return ""


def _immagine(percorso: Path) -> dict:
    dati = base64.standard_b64encode(percorso.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dati}}


def _chiama(client: anthropic.Anthropic, system: str, contenuto: list, schema: dict, log: Callable[[str], None]) -> dict:
    try:
        risposta = client.messages.create(
            model=modello_claude(),
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": contenuto}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError:
        raise ErroreAI("La chiave API Anthropic non è valida.")
    except anthropic.RateLimitError:
        raise ErroreAI("Limite di richieste all'API Anthropic raggiunto: riprova tra qualche minuto.")
    except anthropic.APIStatusError as exc:
        raise ErroreAI(f"Errore dall'API Anthropic ({exc.status_code}): {exc.message}")
    except anthropic.APIConnectionError:
        raise ErroreAI("Impossibile contattare l'API Anthropic (connessione).")
    log(f"AI: stop={risposta.stop_reason} input={risposta.usage.input_tokens} output={risposta.usage.output_tokens}")
    if risposta.stop_reason == "refusal":
        raise ErroreAI("Il modello ha rifiutato la richiesta.")
    if risposta.stop_reason == "max_tokens":
        raise ErroreAI("Risposta del modello troncata: riprova.")
    testo = next((b.text for b in risposta.content if b.type == "text"), "")
    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        raise ErroreAI("Risposta del modello non leggibile.")


SCHEMA_SELEZIONE = {
    "type": "object",
    "properties": {
        "selezioni": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "riga": {"type": "integer", "description": "numero della riga (come nel testo numerato)"},
                    "parola": {"type": "string", "description": "la parola esattamente come compare nella riga"},
                    "timestamp": {"type": "number", "description": "tempo in secondi del fotogramma scelto (etichetta sul foglio)"},
                    "motivo": {"type": "string"},
                },
                "required": ["riga", "parola", "timestamp", "motivo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["selezioni"],
    "additionalProperties": False,
}

SCHEMA_VERIFICA = {
    "type": "object",
    "properties": {
        "verifiche": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "indice": {"type": "integer"},
                    "ok": {"type": "boolean"},
                    "timestamp_alternativo": {"type": "number", "description": "nuovo tempo se ok=false, altrimenti -1"},
                    "motivo": {"type": "string"},
                },
                "required": ["indice", "ok", "timestamp_alternativo", "motivo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verifiche"],
    "additionalProperties": False,
}

SYSTEM = (
    "Prepari esercizi didattici per un ragazzo autistico che ascolta una canzone per bambini guardando il video su YouTube. "
    "Nel testo stampato alcune parole vengono sostituite da un fotogramma del video: il ragazzo guarda l'immagine e scrive "
    "la parola sui trattini. Le immagini devono quindi mostrare in modo chiaro e inequivocabile la cosa, l'animale, "
    "la persona o l'azione indicata dalla parola. Rispondi solo con il JSON richiesto."
)


def _numera(righe: list[str]) -> str:
    return "\n".join(f"{i}: {r}" for i, r in enumerate(righe))


def scegli_parole(righe: list[str], n_parole: int, fogli: list[Path], titolo: str,
                  tempi_validi: list[float], log: Callable[[str], None]) -> list[dict]:
    """Chiede al modello quali parole sostituire e con quale fotogramma."""
    client = _client()
    if n_parole > 0:
        quante = f"Scegli esattamente {n_parole} parole (meno solo se davvero non ci sono abbastanza parole rappresentabili)."
    else:
        quante = ("Decidi tu quante parole: circa una ogni 2-3 righe, tipicamente 5-6 per un testo breve (strofa + ritornello) "
                  "e 10-12 per un testo intero.")
    istruzioni = f"""Canzone: "{titolo}".
Testo numerato per riga:
{_numera(righe)}

Le immagini allegate sono fogli di contatto del video: ogni fotogramma ha stampato sopra il suo tempo in secondi.

Compito:
1. {quante}
2. Scegli solo parole concrete: nomi di cose, animali, persone, luoghi (es. toro, arena, letto, folla) oppure verbi di azioni
   ben visibili (es. dorme, corre). Mai articoli, preposizioni, avverbi, aggettivi o nomi astratti (vicino, delirio, mistero,
   tranquillità, pena) e mai nomi propri di personaggi (Camomillo, Pio): un ragazzo deve poter indovinare la parola
   guardando solo l'immagine. Preferisci parole di 3-10 lettere.
3. Distribuisci le parole lungo tutto il testo; al massimo 2 parole per riga; non scegliere due volte la stessa parola
   (se un ritornello si ripete, sostituisci la parola solo nella prima occorrenza). Non scegliere parole da righe fatte solo di
   vocalizzi (olé, lallara...) a meno che non ci sia proprio nient'altro.
4. Per ogni parola indica il tempo del fotogramma più rappresentativo, copiando l'etichetta in secondi dai fogli di contatto.
   Il soggetto deve essere grande, ben visibile e riconoscibile anche in una stampa di 3 cm.
5. "parola" deve essere copiata esattamente come appare nella riga indicata (stessa forma, singolare/plurale, accenti)."""
    contenuto = [_immagine(f) for f in fogli] + [{"type": "text", "text": istruzioni}]
    dati = _chiama(client, SYSTEM, contenuto, SCHEMA_SELEZIONE, log)
    return _ripulisci_selezioni(dati.get("selezioni", []), righe, tempi_validi, log)


def _tempo_vicino(t: float, tempi_validi: list[float]) -> float:
    return min(tempi_validi, key=lambda v: abs(v - t))


def _ripulisci_selezioni(selezioni: list[dict], righe: list[str], tempi_validi: list[float],
                         log: Callable[[str], None]) -> list[dict]:
    """Scarta scelte incoerenti (riga inesistente, parola assente) e limita a 2 per riga."""
    valide: list[dict] = []
    per_riga: dict[int, int] = {}
    usate: set[str] = set()
    for s in selezioni:
        try:
            riga = int(s["riga"])
            parola = str(s["parola"]).strip().strip(".,;:!?\"'()")
            t = float(s["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if riga < 0 or riga >= len(righe) or not parola:
            log(f"scarto: riga {riga} non valida per '{parola}'")
            continue
        candidate = {p.lower(): p for p in parole_candidate(righe[riga])}
        if parola.lower() not in candidate:
            # prova a cercarla in una riga vicina (il modello a volte sbaglia il numero)
            trovata = None
            for delta in (1, -1, 2, -2):
                j = riga + delta
                if 0 <= j < len(righe) and parola.lower() in {p.lower() for p in parole_candidate(righe[j])}:
                    trovata = j
                    break
            if trovata is None:
                log(f"scarto: '{parola}' non è nella riga {riga}")
                continue
            riga = trovata
            candidate = {p.lower(): p for p in parole_candidate(righe[riga])}
        parola = candidate[parola.lower()]
        if parola.lower() in usate or per_riga.get(riga, 0) >= 2:
            continue
        usate.add(parola.lower())
        per_riga[riga] = per_riga.get(riga, 0) + 1
        valide.append({"riga": riga, "parola": parola, "timestamp": _tempo_vicino(t, tempi_validi),
                       "motivo": str(s.get("motivo", ""))[:200]})
    valide.sort(key=lambda s: (s["riga"], righe[s["riga"]].lower().find(s["parola"].lower())))
    return valide


def verifica_fotogrammi(selezioni: list[dict], immagini: list[Path], fogli: list[Path],
                        tempi_validi: list[float], log: Callable[[str], None]) -> list[dict]:
    """Mostra al modello ogni fotogramma scelto: conferma oppure propone un altro tempo."""
    client = _client()
    contenuto: list = [{"type": "text", "text": "Fogli di contatto del video (per scegliere eventuali alternative):"}]
    contenuto += [_immagine(f) for f in fogli]
    for i, (s, img) in enumerate(zip(selezioni, immagini)):
        contenuto.append({"type": "text", "text": f"Immagine {i}: parola \"{s['parola']}\" (fotogramma a {s['timestamp']}s)"})
        contenuto.append(_immagine(img))
    contenuto.append({"type": "text", "text": (
        "Per ogni immagine numerata: il fotogramma rappresenta chiaramente la parola, in modo che un ragazzo "
        "la riconosca senza dubbi guardando una stampa di 3 cm? Se sì, ok=true e timestamp_alternativo=-1. "
        "Se no (soggetto assente, piccolo, tagliato, sfocato, scena di transizione, testo sovrapposto), ok=false e "
        "indica in timestamp_alternativo il tempo di un fotogramma migliore preso dai fogli di contatto."
    )})
    dati = _chiama(client, SYSTEM, contenuto, SCHEMA_VERIFICA, log)
    esiti = {int(v["indice"]): v for v in dati.get("verifiche", []) if isinstance(v, dict) and "indice" in v}
    risultato = []
    for i, s in enumerate(selezioni):
        v = esiti.get(i)
        if v is None or v.get("ok", True):
            risultato.append({**s, "verificata": True})
            continue
        try:
            alt = float(v.get("timestamp_alternativo", -1))
        except (TypeError, ValueError):
            alt = -1
        if alt >= 0:
            nuovo = _tempo_vicino(alt, tempi_validi)
            log(f"'{s['parola']}': fotogramma {s['timestamp']}s scartato ({v.get('motivo', '')}), nuovo {nuovo}s")
            risultato.append({**s, "timestamp": nuovo, "verificata": False, "motivo_verifica": str(v.get("motivo", ""))[:200]})
        else:
            risultato.append({**s, "verificata": True})
    return risultato


def pulisci_nome_file(parola: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", parola.lower().replace("è", "e").replace("é", "e").replace("à", "a")
                  .replace("ì", "i").replace("ò", "o").replace("ù", "u")).strip("_")
    return base or "parola"
