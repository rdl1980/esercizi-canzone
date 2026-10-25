"""Configurazione letta da variabili d'ambiente (file .env) e, in modalità locale, da impostazioni.json."""
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # cartella webapp/ (o cartella temporanea di PyInstaller)
load_dotenv(BASE_DIR / ".env")


def _bool(nome: str, default: bool) -> bool:
    v = os.environ.get(nome)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "si", "sì", "yes", "on")


# Modalità locale = app installata sul PC: un solo utente, senza login, chiave API dalle impostazioni
MODALITA_LOCALE = _bool("MODALITA_LOCALE", False)

DATA_DIR = Path(os.environ.get("DATA_DIR") or (BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ESERCIZI_DIR = DATA_DIR / "esercizi"
ESERCIZI_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
IMPOSTAZIONI_PATH = DATA_DIR / "impostazioni.json"

# Cartella in cui copiare anche i PDF finiti (es. Documenti\Esercizi canzone); vuota = nessuna copia
ESPORTA_PDF_DIR = Path(os.environ["ESPORTA_PDF_DIR"]).resolve() if os.environ.get("ESPORTA_PDF_DIR") else None


def _secret_key() -> str:
    k = os.environ.get("SECRET_KEY", "").strip()
    if k:
        return k
    f = DATA_DIR / ".secret_key"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    k = secrets.token_urlsafe(48)
    f.write_text(k, encoding="utf-8")
    return k


SECRET_KEY = _secret_key()
SESSIONE_GIORNI = int(os.environ.get("SESSIONE_GIORNI", "30"))
COOKIE_SICURO = _bool("COOKIE_SICURO", False)  # True solo dietro HTTPS

MODELLO_PREDEFINITO = "claude-sonnet-5-5"
CHIAVI_IMPOSTAZIONI = ("ANTHROPIC_API_KEY", "CLAUDE_MODEL")


def carica_impostazioni() -> dict:
    """Legge impostazioni.json (modalità locale) e le mette nell'ambiente se non già presenti."""
    if not IMPOSTAZIONI_PATH.exists():
        return {}
    try:
        dati = json.loads(IMPOSTAZIONI_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for k in CHIAVI_IMPOSTAZIONI:
        if dati.get(k) and not os.environ.get(k):
            os.environ[k] = str(dati[k]).strip()
    return dati


def salva_impostazioni(**valori: str) -> None:
    dati = {}
    if IMPOSTAZIONI_PATH.exists():
        try:
            dati = json.loads(IMPOSTAZIONI_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            dati = {}
    for k, v in valori.items():
        if k not in CHIAVI_IMPOSTAZIONI:
            continue
        v = (v or "").strip()
        dati[k] = v
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    IMPOSTAZIONI_PATH.write_text(json.dumps(dati, indent=1), encoding="utf-8")


if MODALITA_LOCALE:
    carica_impostazioni()


def chiave_api() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def modello_claude() -> str:
    return os.environ.get("CLAUDE_MODEL", "").strip() or MODELLO_PREDEFINITO


# compatibilità con il codice che importa le costanti
ANTHROPIC_API_KEY = chiave_api()
CLAUDE_MODEL = modello_claude()

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
YTDLP_BIN = os.environ.get("YTDLP_BIN", "yt-dlp")
# Secondo tentativo di download con il client standard + componenti remoti (richiede node/deno)
YTDLP_REMOTE_COMPONENTS = _bool("YTDLP_REMOTE_COMPONENTS", True)

INTERVALLO_FOTOGRAMMI = float(os.environ.get("INTERVALLO_FOTOGRAMMI", "2.5"))  # secondi
DURATA_MAX_VIDEO = int(os.environ.get("DURATA_MAX_VIDEO", "900"))  # secondi
MAX_PAROLE = 30
