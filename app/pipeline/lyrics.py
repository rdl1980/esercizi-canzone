"""Preparazione del testo: blocchi (strofe), prima strofa + ritornello, compressione dei ritornelli non lessicali."""
import re
import unicodedata

# Sillabe/vocalizzi che non sono parole vere ("olé", "lallara", "na na na", "oh oh")
_SILLABE = {
    "la", "le", "lo", "li", "lu", "na", "ne", "ni", "no", "nu", "oh", "ah", "eh", "uh", "ih", "o", "a", "e", "u",
    "ole", "olè", "olé", "yeah", "ye", "yo", "hey", "ehi", "tra", "ra", "re", "ri", "ro", "ru", "dum", "dam", "dim",
    "du", "da", "de", "do", "doo", "di", "pa", "pam", "pum", "para", "bam", "ba", "bum", "bom", "sha", "wop",
    "ta", "tam", "tum", "tu", "ti", "to", "zum", "zim", "zam", "hmm", "mm", "um", "lalla", "lallara", "lara",
    "lal", "lol", "lui", "wo", "ua", "uè", "ue", "ay", "ai", "ey", "hop", "op", "ups", "ups", "ciu", "ciuf", "tic", "tac",
    "din", "don", "dan", "sci", "scia", "pim", "pom", "plin", "plon",
}


def _pulisci_token(tok: str) -> str:
    tok = tok.lower()
    tok = re.sub(r"[^\w]", "", tok)
    tok = re.sub(r"([aeiouhmn])\1+", r"\1", tok)  # "ooooh" -> "oh", "mmmm" -> "m"
    return tok


def e_non_lessicale(riga: str) -> bool:
    token = [t for t in re.split(r"[\s\-–—]+", riga.strip()) if t]
    puliti = [_pulisci_token(t) for t in token]
    puliti = [t for t in puliti if t]
    if not puliti:
        return False
    return all(t in _SILLABE for t in puliti)


def normalizza_riga(riga: str) -> str:
    r = unicodedata.normalize("NFKC", riga).strip().lower()
    r = re.sub(r"[^\w\s']", " ", r)
    return re.sub(r"\s+", " ", r).strip()


def in_blocchi(testo: str) -> list[list[str]]:
    """Divide il testo in blocchi separati da righe vuote; ogni blocco è una lista di righe pulite."""
    testo = unicodedata.normalize("NFKC", testo.replace("\r\n", "\n").replace("\r", "\n"))
    blocchi: list[list[str]] = []
    corrente: list[str] = []
    for riga in testo.split("\n"):
        riga = re.sub(r"\s+", " ", riga).strip()
        if not riga:
            if corrente:
                blocchi.append(corrente)
                corrente = []
            continue
        corrente.append(riga)
    if corrente:
        blocchi.append(corrente)
    return blocchi


def _firma(blocco: list[str]) -> str:
    return "\n".join(normalizza_riga(r) for r in blocco)


def prima_strofa_e_ritornello(blocchi: list[list[str]]) -> list[list[str]]:
    """Tiene la prima strofa e il ritornello (il primo blocco che si ripete nel testo)."""
    if len(blocchi) >= 2:
        firme = [_firma(b) for b in blocchi]
        conteggi = {f: firme.count(f) for f in firme}
        ritornello_idx = next((i for i, f in enumerate(firme) if conteggi[f] >= 2 and i > 0), None)
        if ritornello_idx is None:
            ritornello_idx = next((i for i, f in enumerate(firme) if conteggi[f] >= 2), None)
        if ritornello_idx is None:
            return blocchi[:2]
        if ritornello_idx == 0:
            # il ritornello apre il brano: ritornello + prima strofa diversa
            strofa = next((b for i, b in enumerate(blocchi) if firme[i] != firme[0]), None)
            return [blocchi[0]] + ([strofa] if strofa else [])
        return [blocchi[0], blocchi[ritornello_idx]]
    # un solo blocco: cerca una sequenza di righe (>= 2) che si ripete
    righe = blocchi[0] if blocchi else []
    norm = [normalizza_riga(r) for r in righe]
    n = len(norm)
    migliore = None  # (lunghezza, inizio)
    for lung in range(min(8, n // 2), 1, -1):
        for i in range(0, n - lung + 1):
            seq = norm[i:i + lung]
            if any(not s for s in seq):
                continue
            for j in range(i + lung, n - lung + 1):
                if norm[j:j + lung] == seq:
                    migliore = (lung, i)
                    break
            if migliore:
                break
        if migliore:
            break
    if migliore is None:
        return [righe[:8]] if righe else []
    lung, inizio = migliore
    ritornello = righe[inizio:inizio + lung]
    if inizio > 0:
        return [righe[:inizio], ritornello]
    # il ritornello apre il brano: ritornello + le righe fino alla sua ripetizione
    return [ritornello, righe[lung:lung + 8]]


def comprimi_ritornelli(blocchi: list[list[str]]) -> list[list[str]]:
    """Dentro ogni blocco: righe identiche consecutive -> una sola; vocalizzi ripetuti -> una sola riga per blocco."""
    risultato: list[list[str]] = []
    for blocco in blocchi:
        nuove: list[str] = []
        viste_non_lessicali: set[str] = set()
        for riga in blocco:
            chiave = normalizza_riga(riga)
            if nuove and normalizza_riga(nuove[-1]) == chiave:
                continue
            if e_non_lessicale(riga):
                if chiave in viste_non_lessicali:
                    continue
                viste_non_lessicali.add(chiave)
            nuove.append(riga)
        if nuove:
            risultato.append(nuove)
    return risultato


def prepara_testo(testo: str, modalita: str) -> list[list[str]]:
    blocchi = in_blocchi(testo)
    if modalita == "strofa":
        blocchi = prima_strofa_e_ritornello(blocchi)
    return comprimi_ritornelli(blocchi)


def righe_piatte(blocchi: list[list[str]]) -> list[str]:
    return [r for b in blocchi for r in b]


_SEGMENTI_DA_SCARTARE = re.compile(
    r"zecchino|antoniano|piccolo coro|canzon[ei] per bambini|canzone per bambini|official|ufficiale|video ufficiale|"
    r"\blyrics?\b|\btesto\b|karaoke|\bhd\b|\b4k\b|cartoon|cartone|sigla|\bvevo\b|\btopic\b|edizione|\blive\b|"
    r"\bfeat\.?\b|\bft\.?\b|\d+\s*[°ºa]\b|\bversione\b|\bcover\b|\bremix\b|\bmix\b|\bfull\b|\bcompilation\b",
    re.IGNORECASE,
)
_SEPARATORI = re.compile(r"\s+[-–—|:·•]\s+|\s*[|•]\s*")


def pulisci_titolo_video(titolo: str, canale: str = "") -> str:
    """Dal titolo YouTube ("Canale - Canzone (cartoon) - 23° Zecchino d'Oro") tiene solo il nome della canzone."""
    t = unicodedata.normalize("NFKC", titolo or "")
    t = "".join(c for c in t if unicodedata.category(c) not in ("So", "Cs", "Co", "Cc", "Cf"))  # emoji, simboli, ZWJ
    t = t.replace("︎", "").replace("️", "")  # selettori di variante degli emoji
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", t)  # (cartoon), [official video]
    t = re.sub(r"\s+", " ", t).strip(" -–—|:·•\t")
    if not t:
        return ""
    segmenti = [s.strip(" -–—|:·•\"'“”‘’") for s in _SEPARATORI.split(t)]
    segmenti = [s for s in segmenti if s]
    canale_norm = (canale or "").strip().lower()
    buoni = []
    for s in segmenti:
        if canale_norm and (s.lower() == canale_norm or s.lower() in canale_norm or canale_norm in s.lower()):
            continue
        if _SEGMENTI_DA_SCARTARE.search(s):
            continue
        buoni.append(s)
    if not buoni:
        buoni = [max(segmenti, key=len)] if segmenti else [t]
    scelto = buoni[-1] if len(buoni) > 1 else buoni[0]
    scelto = re.sub(r"\s+", " ", scelto).strip(" -–—|:·•.,")
    lettere = [c for c in scelto if c.isalpha()]
    if lettere and all(c.isupper() for c in lettere):  # "IL COCCODRILLO COME FA?" -> "Il coccodrillo come fa?"
        scelto = scelto.lower()
    return scelto[:1].upper() + scelto[1:] if scelto else ""


def parole_candidate(riga: str) -> list[str]:
    """Parole di almeno 3 lettere nella riga (per controllare le scelte dell'AI)."""
    return [p for p in re.findall(r"[^\W\d_]+", riga) if len(p) >= 3]
