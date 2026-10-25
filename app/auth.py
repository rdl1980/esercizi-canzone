"""Password con bcrypt e sessione in cookie firmato."""
import re
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import COOKIE_SICURO, MODALITA_LOCALE, SECRET_KEY, SESSIONE_GIORNI
from .db import adesso, db

COOKIE_NOME = "sessione"
EMAIL_LOCALE = "locale@questo-pc"


def utente_locale():
    """In modalità locale c'è un solo utente, creato al primo avvio, senza password utilizzabile."""
    with db() as conn:
        riga = conn.execute("SELECT id, email FROM utenti WHERE email = ?", (EMAIL_LOCALE,)).fetchone()
        if riga is None:
            import secrets

            conn.execute("INSERT INTO utenti (email, password_hash, creato_il) VALUES (?, ?, ?)",
                         (EMAIL_LOCALE, hash_password(secrets.token_urlsafe(32)), adesso()))
            riga = conn.execute("SELECT id, email FROM utenti WHERE email = ?", (EMAIL_LOCALE,)).fetchone()
    return riga
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="sessione-utente")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verifica_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def crea_token(utente_id: int) -> str:
    return _serializer.dumps({"uid": utente_id})


def leggi_token(token: str) -> Optional[int]:
    try:
        dati = _serializer.loads(token, max_age=SESSIONE_GIORNI * 86400)
    except (BadSignature, SignatureExpired):
        return None
    return dati.get("uid")


def imposta_cookie(response, utente_id: int) -> None:
    response.set_cookie(
        COOKIE_NOME,
        crea_token(utente_id),
        max_age=SESSIONE_GIORNI * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SICURO,
    )


def cancella_cookie(response) -> None:
    response.delete_cookie(COOKIE_NOME)


def utente_corrente(request: Request):
    """Restituisce la riga utente oppure None."""
    if MODALITA_LOCALE:
        return utente_locale()
    token = request.cookies.get(COOKIE_NOME)
    if not token:
        return None
    uid = leggi_token(token)
    if uid is None:
        return None
    with db() as conn:
        return conn.execute("SELECT id, email FROM utenti WHERE id = ?", (uid,)).fetchone()


def richiedi_utente(request: Request):
    """Dipendenza per le API: 401 se non autenticato."""
    utente = utente_corrente(request)
    if utente is None:
        raise HTTPException(status_code=401, detail="Devi accedere per usare questa funzione.")
    return utente


def valida_credenziali(email: str, password: str) -> str:
    email = (email or "").strip().lower()
    if not email or not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Inserisci un indirizzo email valido.")
    if not password or len(password) < 8:
        raise HTTPException(status_code=422, detail="La password deve avere almeno 8 caratteri.")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="La password è troppo lunga (massimo 72 caratteri).")
    return email
