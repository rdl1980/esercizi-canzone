"""Applicazione FastAPI: API REST (/api/...) e pagine HTML."""
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import auth, jobs
from .config import (ESPORTA_PDF_DIR, MAX_PAROLE, MODALITA_LOCALE, MODELLO_PREDEFINITO, chiave_api, modello_claude,
                     salva_impostazioni)
from .db import adesso, db, inizializza
from .pipeline.run import cartella_esercizio
from .pipeline.youtube import estrai_video_id
from .versione import VERSIONE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

MODALITA = {"completo": "Testo completo", "strofa": "Prima strofa + ritornello"}
STATI_ETICHETTA = {"coda": "In coda", "in_lavorazione": "In lavorazione", "pronto": "Pronto", "errore": "Errore"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    inizializza()
    jobs.avvia_worker()
    yield


app = FastAPI(title="Esercizi canzone", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


# --------------------------------------------------------------------------- errori in italiano
_CAMPI = {"url": "il link YouTube", "testo": "il testo", "n_parole": "il numero di parole", "titolo": "il titolo",
          "modalita": "la modalità", "email": "l'email", "password": "la password"}


@app.exception_handler(HTTPException)
async def errore_http(request: Request, exc: HTTPException):
    dettaglio = exc.detail
    if dettaglio == "There was an error parsing the body":
        dettaglio = "Dati inviati non validi (il corpo della richiesta non è JSON corretto)."
    return JSONResponse(status_code=exc.status_code, content={"detail": dettaglio}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def errore_validazione(request: Request, exc: RequestValidationError):
    for err in exc.errors():
        campo = next((str(p) for p in err.get("loc", []) if str(p) in _CAMPI), None)
        if campo:
            if err.get("type", "").startswith("int"):
                return JSONResponse(status_code=422,
                                    content={"detail": f"Valore non valido per {_CAMPI[campo]}: serve un numero intero."})
            return JSONResponse(status_code=422, content={"detail": f"Valore non valido per {_CAMPI[campo]}."})
    return JSONResponse(status_code=422, content={"detail": "Dati inviati non validi."})


# --------------------------------------------------------------------------- modelli
class Credenziali(BaseModel):
    email: str = ""
    password: str = ""


class ParametriEsercizio(BaseModel):
    url: Optional[str] = None
    testo: Optional[str] = None
    n_parole: Optional[int] = None
    titolo: Optional[str] = None
    modalita: Optional[str] = None


def valida_parametri(p: ParametriEsercizio, esistente: Optional[dict] = None) -> dict:
    """Controlla i campi e restituisce i valori definitivi (completando con l'esercizio esistente, se c'è)."""
    e = esistente or {}
    url = (p.url if p.url is not None else e.get("url", "")) or ""
    url = url.strip()
    if not url:
        raise HTTPException(422, "Inserisci il link del video YouTube.")
    video_id = estrai_video_id(url)
    if not video_id:
        raise HTTPException(422, "Il link non sembra un video YouTube valido (es. https://www.youtube.com/watch?v=...).")

    testo = (p.testo if p.testo is not None else e.get("testo", "")) or ""
    testo = testo.replace("\r\n", "\n").strip()
    parole_testo = [w for w in testo.split() if any(c.isalpha() for c in w)]
    if len(testo) < 20 or len(parole_testo) < 6:
        raise HTTPException(422, "Il testo della canzone è troppo corto: incolla almeno qualche riga (minimo 6 parole).")
    if len(testo) > 12000:
        raise HTTPException(422, "Il testo è troppo lungo (massimo 12.000 caratteri).")

    n_parole = p.n_parole if p.n_parole is not None else int(e.get("n_parole", 0) or 0)
    if n_parole < 0 or n_parole > MAX_PAROLE:
        raise HTTPException(422, f"Il numero di parole deve essere tra 0 (decidi tu) e {MAX_PAROLE}.")

    modalita = (p.modalita if p.modalita is not None else e.get("modalita", "completo")) or "completo"
    if modalita not in MODALITA:
        raise HTTPException(422, "Modalità non valida: usa 'completo' oppure 'strofa'.")

    titolo = (p.titolo if p.titolo is not None else e.get("titolo", "")) or ""
    titolo = " ".join(titolo.split())
    if len(titolo) > 100:
        raise HTTPException(422, "Il titolo è troppo lungo (massimo 100 caratteri).")

    return {"url": url, "video_id": video_id, "testo": testo, "n_parole": n_parole, "modalita": modalita,
            "titolo": titolo or None}


def controlla_chiave_ai() -> None:
    if not chiave_api():
        if MODALITA_LOCALE:
            raise HTTPException(503, "Manca la chiave API Anthropic: inseriscila nella pagina Impostazioni.")
        raise HTTPException(503, "Il server non ha la chiave API Anthropic configurata (ANTHROPIC_API_KEY nel file .env).")


@app.get("/api/versione")
def api_versione():
    return {"app": "esercizi-canzone", "versione": VERSIONE, "locale": MODALITA_LOCALE}


# --------------------------------------------------------------------------- impostazioni (solo modalità locale)
class Impostazioni(BaseModel):
    chiave: Optional[str] = None
    modello: Optional[str] = None


def _solo_locale() -> None:
    if not MODALITA_LOCALE:
        raise HTTPException(404, "Le impostazioni si cambiano nel file .env del server.")


@app.get("/api/impostazioni")
def api_impostazioni(utente=Depends(auth.richiedi_utente)):
    _solo_locale()
    chiave = chiave_api()
    return {"chiave_presente": bool(chiave), "chiave_fine": chiave[-4:] if chiave else "",
            "modello": modello_claude(), "modello_predefinito": MODELLO_PREDEFINITO,
            "cartella_pdf": str(ESPORTA_PDF_DIR) if ESPORTA_PDF_DIR else None}


@app.post("/api/impostazioni")
def api_salva_impostazioni(p: Impostazioni, utente=Depends(auth.richiedi_utente)):
    _solo_locale()
    from .pipeline.ai import prova_chiave

    chiave = (p.chiave or "").strip() or chiave_api()
    modello = (p.modello or "").strip() or MODELLO_PREDEFINITO
    if not chiave:
        raise HTTPException(422, "Inserisci la chiave API Anthropic (inizia con sk-ant-).")
    if not chiave.startswith("sk-ant-") or len(chiave) < 20:
        raise HTTPException(422, "La chiave non sembra una chiave API Anthropic: deve iniziare con sk-ant-.")
    if not all(c.isalnum() or c in "-._" for c in modello):
        raise HTTPException(422, "Nome del modello non valido.")
    errore = prova_chiave(chiave, modello)
    if errore:
        raise HTTPException(422, errore)
    salva_impostazioni(ANTHROPIC_API_KEY=chiave, CLAUDE_MODEL=modello)
    return {"ok": True, "chiave_fine": chiave[-4:], "modello": modello}


# --------------------------------------------------------------------------- API autenticazione
@app.post("/api/auth/registrazione", status_code=201)
def api_registrazione(c: Credenziali):
    email = auth.valida_credenziali(c.email, c.password)
    with db() as conn:
        if conn.execute("SELECT 1 FROM utenti WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "Esiste già un account con questa email.")
        cur = conn.execute("INSERT INTO utenti (email, password_hash, creato_il) VALUES (?, ?, ?)",
                           (email, auth.hash_password(c.password), adesso()))
        uid = cur.lastrowid
    risposta = JSONResponse(status_code=201, content={"id": uid, "email": email})
    auth.imposta_cookie(risposta, uid)
    return risposta


@app.post("/api/auth/login")
def api_login(c: Credenziali):
    email = (c.email or "").strip().lower()
    with db() as conn:
        riga = conn.execute("SELECT id, password_hash FROM utenti WHERE email = ?", (email,)).fetchone()
    if riga is None or not auth.verifica_password(c.password or "", riga["password_hash"]):
        raise HTTPException(401, "Email o password non corretti.")
    risposta = JSONResponse(content={"id": riga["id"], "email": email})
    auth.imposta_cookie(risposta, riga["id"])
    return risposta


@app.post("/api/auth/logout")
def api_logout():
    risposta = JSONResponse(content={"ok": True})
    auth.cancella_cookie(risposta)
    return risposta


@app.get("/api/auth/me")
def api_me(utente=Depends(auth.richiedi_utente)):
    return {"id": utente["id"], "email": utente["email"]}


# --------------------------------------------------------------------------- API esercizi
def _serializza(r) -> dict:
    d = dict(r)
    d["stato_etichetta"] = STATI_ETICHETTA.get(d["stato"], d["stato"])
    d["modalita_etichetta"] = MODALITA.get(d["modalita"], d["modalita"])
    try:
        d["parole"] = json.loads(d["parole"]) if d.get("parole") else []
    except json.JSONDecodeError:
        d["parole"] = []
    d.pop("utente_id", None)
    d["titolo_mostrato"] = d.get("titolo") or d.get("titolo_canzone") or d.get("titolo_video") or "Esercizio senza titolo"
    d["pdf_url"] =f"/api/esercizi/{d['id']}/pdf" if d["stato"] == "pronto" else None
    d["anteprima_url"] = f"/api/esercizi/{d['id']}/anteprima.png" if d["stato"] == "pronto" else None
    return d


def carica_esercizio(esercizio_id: int, utente) -> dict:
    with db() as conn:
        r = conn.execute("SELECT * FROM esercizi WHERE id = ? AND utente_id = ?", (esercizio_id, utente["id"])).fetchone()
    if r is None:
        raise HTTPException(404, "Esercizio non trovato.")
    return dict(r)


@app.get("/api/esercizi")
def api_elenco(utente=Depends(auth.richiedi_utente)):
    with db() as conn:
        righe = conn.execute("SELECT * FROM esercizi WHERE utente_id = ? ORDER BY creato_il DESC, id DESC",
                             (utente["id"],)).fetchall()
    return {"esercizi": [_serializza(r) for r in righe]}


@app.post("/api/esercizi", status_code=202)
def api_crea(p: ParametriEsercizio, utente=Depends(auth.richiedi_utente)):
    valori = valida_parametri(p)
    controlla_chiave_ai()
    ora = adesso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO esercizi (utente_id, titolo, url, video_id, testo, n_parole, modalita, stato, fase, creato_il, aggiornato_il)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'coda', 'In attesa', ?, ?)",
            (utente["id"], valori["titolo"], valori["url"], valori["video_id"], valori["testo"],
             valori["n_parole"], valori["modalita"], ora, ora))
        eid = cur.lastrowid
    jobs.accoda(eid)
    return _serializza(carica_esercizio(eid, utente))


@app.get("/api/esercizi/{esercizio_id}")
def api_dettaglio(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    return _serializza(carica_esercizio(esercizio_id, utente))


@app.post("/api/esercizi/{esercizio_id}/rigenera", status_code=202)
def api_rigenera(esercizio_id: int, p: ParametriEsercizio, utente=Depends(auth.richiedi_utente)):
    e = carica_esercizio(esercizio_id, utente)
    if e["stato"] in ("coda", "in_lavorazione"):
        raise HTTPException(409, "La generazione è già in corso: attendi che finisca.")
    valori = valida_parametri(p, e)
    controlla_chiave_ai()
    with db() as conn:
        conn.execute(
            "UPDATE esercizi SET titolo=?, url=?, video_id=?, testo=?, n_parole=?, modalita=?, parole=NULL, completato_il=NULL,"
            " aggiornato_il=? WHERE id=?",
            (valori["titolo"], valori["url"], valori["video_id"], valori["testo"], valori["n_parole"], valori["modalita"],
             adesso(), esercizio_id))
    jobs.accoda(esercizio_id)
    return _serializza(carica_esercizio(esercizio_id, utente))


@app.delete("/api/esercizi/{esercizio_id}", status_code=204)
def api_elimina(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    e = carica_esercizio(esercizio_id, utente)
    if e["stato"] == "in_lavorazione":
        raise HTTPException(409, "L'esercizio è in lavorazione: attendi che finisca prima di eliminarlo.")
    with db() as conn:
        conn.execute("DELETE FROM esercizi WHERE id = ?", (esercizio_id,))
    shutil.rmtree(cartella_esercizio(esercizio_id), ignore_errors=True)
    return Response(status_code=204)


def _file_pronto(esercizio_id: int, utente, nome: str, media: str, scarica: bool = False):
    e = carica_esercizio(esercizio_id, utente)
    f = cartella_esercizio(esercizio_id) / nome
    if e["stato"] != "pronto" or not f.exists():
        raise HTTPException(404, "Il file non è ancora disponibile.")
    nome_download = None
    if scarica:
        titolo = e["titolo"] or e.get("titolo_canzone") or "esercizio"
        base = "".join(c if c.isalnum() or c in " -_" else "_" for c in titolo).strip() or "esercizio"
        nome_download = f"{base}.pdf"
    return FileResponse(str(f), media_type=media, filename=nome_download, headers={"Cache-Control": "no-store"})


@app.get("/api/esercizi/{esercizio_id}/pdf")
def api_pdf(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    return _file_pronto(esercizio_id, utente, "esercizio.pdf", "application/pdf", scarica=True)


@app.get("/api/esercizi/{esercizio_id}/pdf/apri")
def api_pdf_apri(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    return _file_pronto(esercizio_id, utente, "esercizio.pdf", "application/pdf")


@app.get("/api/esercizi/{esercizio_id}/anteprima.png")
def api_anteprima(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    return _file_pronto(esercizio_id, utente, "anteprima.png", "image/png")


@app.get("/api/esercizi/{esercizio_id}/esercizio.json")
def api_json(esercizio_id: int, utente=Depends(auth.richiedi_utente)):
    return _file_pronto(esercizio_id, utente, "esercizio.json", "application/json")


# --------------------------------------------------------------------------- pagine HTML
def _pagina(request: Request, nome: str, **ctx) -> HTMLResponse:
    utente = auth.utente_corrente(request)
    return templates.TemplateResponse(request, nome, {"utente": utente, "MODALITA": MODALITA, "MAX_PAROLE": MAX_PAROLE,
                                                      "LOCALE": MODALITA_LOCALE, "VERSIONE": VERSIONE,
                                                      "chiave_ai": bool(chiave_api()), **ctx})


def _richiedi_pagina(request: Request):
    utente = auth.utente_corrente(request)
    if utente is None:
        return None
    return utente


@app.get("/", response_class=HTMLResponse)
def pagina_home(request: Request):
    if _richiedi_pagina(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _pagina(request, "elenco.html")


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request):
    if auth.utente_corrente(request):
        return RedirectResponse("/", status_code=303)
    return _pagina(request, "login.html")


@app.get("/registrati", response_class=HTMLResponse)
def pagina_registrazione(request: Request):
    if auth.utente_corrente(request):
        return RedirectResponse("/", status_code=303)
    return _pagina(request, "registrati.html")


@app.get("/nuovo", response_class=HTMLResponse)
def pagina_nuovo(request: Request):
    if _richiedi_pagina(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _pagina(request, "nuovo.html")


@app.get("/impostazioni", response_class=HTMLResponse)
def pagina_impostazioni(request: Request):
    if not MODALITA_LOCALE:
        return RedirectResponse("/", status_code=303)
    return _pagina(request, "impostazioni.html", modello=modello_claude(), modello_predefinito=MODELLO_PREDEFINITO,
                   chiave_fine=chiave_api()[-4:], cartella_pdf=str(ESPORTA_PDF_DIR) if ESPORTA_PDF_DIR else None)


@app.get("/esercizi/{esercizio_id}", response_class=HTMLResponse)
def pagina_esercizio(request: Request, esercizio_id: int):
    utente = _richiedi_pagina(request)
    if utente is None:
        return RedirectResponse("/login", status_code=303)
    try:
        e = carica_esercizio(esercizio_id, utente)
    except HTTPException:
        return _pagina(request, "non_trovato.html")
    return _pagina(request, "esercizio.html", esercizio=_serializza(e))
