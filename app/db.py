"""Accesso a SQLite. Una connessione per richiesta, schema creato all'avvio."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    creato_il TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS esercizi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER NOT NULL REFERENCES utenti(id) ON DELETE CASCADE,
    titolo TEXT,
    titolo_video TEXT,
    titolo_canzone TEXT,
    url TEXT NOT NULL,
    video_id TEXT NOT NULL,
    testo TEXT NOT NULL,
    n_parole INTEGER NOT NULL DEFAULT 0,
    modalita TEXT NOT NULL DEFAULT 'completo',
    stato TEXT NOT NULL DEFAULT 'coda',
    fase TEXT,
    progresso INTEGER NOT NULL DEFAULT 0,
    errore TEXT,
    durata_video REAL,
    parole TEXT,
    creato_il TEXT NOT NULL,
    aggiornato_il TEXT NOT NULL,
    completato_il TEXT
);
CREATE INDEX IF NOT EXISTS idx_esercizi_utente ON esercizi(utente_id, creato_il);
"""


def adesso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connetti() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    conn = connetti()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inizializza() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        colonne = {r["name"] for r in conn.execute("PRAGMA table_info(esercizi)")}
        if "titolo_canzone" not in colonne:  # database creati prima dell'aggiunta della colonna
            conn.execute("ALTER TABLE esercizi ADD COLUMN titolo_canzone TEXT")
            # le vecchie generazioni copiavano il titolo YouTube grezzo nel titolo scelto dall'utente
            conn.execute("UPDATE esercizi SET titolo = NULL WHERE titolo = titolo_video")


def aggiorna_esercizio(esercizio_id: int, **campi) -> None:
    """Aggiorna alcune colonne di un esercizio (usato anche dal worker)."""
    if not campi:
        return
    campi["aggiornato_il"] = adesso()
    set_sql = ", ".join(f"{k} = ?" for k in campi)
    with db() as conn:
        conn.execute(
            f"UPDATE esercizi SET {set_sql} WHERE id = ?",
            [*campi.values(), esercizio_id],
        )
