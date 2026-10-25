"""Controllo del link e download del video (yt-dlp)."""
import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from ..config import YTDLP_BIN, YTDLP_REMOTE_COMPONENTS

YOUTUBE_RE = re.compile(
    r"^(?:https?://)?(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?:[?&#]|$)"
)


class VideoNonDisponibile(Exception):
    pass


def estrai_video_id(url: str) -> Optional[str]:
    m = YOUTUBE_RE.match((url or "").strip())
    return m.group(1) if m else None


def url_canonico(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _esegui(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )


def _messaggio_errore(stderr: str) -> str:
    testo = stderr.lower()
    if "sign in to confirm your age" in testo or "age-restricted" in testo:
        return "Il video ha una restrizione di età e non può essere scaricato."
    if "private video" in testo:
        return "Il video è privato."
    if "members-only" in testo or "join this channel" in testo:
        return "Il video è riservato agli iscritti del canale."
    if "is not a valid url" in testo or "unsupported url" in testo:
        return "Link non valido."
    if any(s in testo for s in ("video unavailable", "not available", "has been removed", "does not exist", "is unavailable")):
        return "Video non disponibile (rimosso, privato o non raggiungibile)."
    if "http error 429" in testo or "too many requests" in testo:
        return "YouTube ha bloccato temporaneamente i download (troppe richieste): riprova tra qualche minuto."
    righe = [r for r in stderr.strip().splitlines() if r.strip()]
    ultima = righe[-1] if righe else "errore sconosciuto"
    return f"Download non riuscito: {ultima[:300]}"


_ARGS_ANDROID = ["--extractor-args", "youtube:player_client=android"]


def info_video(url: str) -> dict:
    """Legge titolo e durata senza scaricare. Solleva VideoNonDisponibile."""
    base = [YTDLP_BIN, "--no-playlist", "--dump-single-json", "--no-download", "--no-warnings"]
    tentativi = [base + _ARGS_ANDROID + [url]]
    if YTDLP_REMOTE_COMPONENTS:
        tentativi.append(base + ["--remote-components", "ejs:github", url])
    ultimo_errore = ""
    for args in tentativi:
        try:
            p = _esegui(args, timeout=120)
        except subprocess.TimeoutExpired:
            ultimo_errore = "timeout nel contattare YouTube"
            continue
        except FileNotFoundError:
            raise VideoNonDisponibile("yt-dlp non è installato sul server.")
        if p.returncode == 0 and p.stdout.strip():
            try:
                dati = json.loads(p.stdout)
            except json.JSONDecodeError:
                ultimo_errore = "risposta di yt-dlp non leggibile"
                continue
            return {
                "titolo": (dati.get("title") or "").strip(),
                "canale": (dati.get("channel") or dati.get("uploader") or "").strip(),
                "durata": float(dati.get("duration") or 0),
                "is_live": bool(dati.get("is_live")),
            }
        ultimo_errore = p.stderr
    raise VideoNonDisponibile(_messaggio_errore(ultimo_errore))


def scarica_video(url: str, cartella: Path, log: Callable[[str], None]) -> Path:
    """Scarica il video (mp4 360p) e, se esistono, i sottotitoli italiani. Restituisce il percorso del video."""
    cartella.mkdir(parents=True, exist_ok=True)
    for vecchio in cartella.glob("video.*"):
        vecchio.unlink()
    uscita = str(cartella / "video.%(ext)s")
    comuni = [
        YTDLP_BIN, "--no-playlist", "--no-warnings",
        "--write-sub", "--write-auto-sub", "--sub-lang", "it.*,it", "--sub-format", "vtt/srt",
        "--write-info-json", "-o", uscita,
    ]
    tentativi = [
        comuni + _ARGS_ANDROID + ["-f", "18/b[ext=mp4][height<=480]/b", url],
    ]
    if YTDLP_REMOTE_COMPONENTS:
        tentativi.append(
            comuni + ["--remote-components", "ejs:github",
                      "-f", "b[ext=mp4][height<=480]/bv*[height<=480][ext=mp4]+ba[ext=m4a]/b", url]
        )
    ultimo_errore = ""
    for i, args in enumerate(tentativi, 1):
        log(f"yt-dlp tentativo {i}: {' '.join(args)}")
        try:
            p = _esegui(args, timeout=900)
        except subprocess.TimeoutExpired:
            ultimo_errore = "timeout durante il download"
            log(ultimo_errore)
            continue
        log(p.stdout[-2000:])
        if p.returncode == 0:
            video = _trova_video(cartella)
            if video is not None:
                return video
            ultimo_errore = "file video non trovato dopo il download"
        else:
            ultimo_errore = p.stderr
            log(p.stderr[-2000:])
    raise VideoNonDisponibile(_messaggio_errore(ultimo_errore))


def _trova_video(cartella: Path) -> Optional[Path]:
    for ext in ("mp4", "mkv", "webm", "mov"):
        f = cartella / f"video.{ext}"
        if f.exists() and f.stat().st_size > 0:
            return f
    return None


def leggi_sottotitoli(cartella: Path) -> Optional[str]:
    """Testo dei sottotitoli italiani se scaricati (solo informativo)."""
    for f in sorted(cartella.glob("video.*.vtt")) + sorted(cartella.glob("video.*.srt")):
        righe = []
        for r in f.read_text(encoding="utf-8", errors="replace").splitlines():
            r = r.strip()
            if not r or "-->" in r or r.isdigit() or r.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            r = re.sub(r"<[^>]+>", "", r)
            if righe and righe[-1] == r:
                continue
            righe.append(r)
        if righe:
            return "\n".join(righe)
    return None
