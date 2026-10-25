"""ffmpeg e yt-dlp per l'app locale: scaricati al primo avvio in %LOCALAPPDATA%\\EserciziCanzone\\bin,
yt-dlp aggiornato da solo (yt-dlp -U) al massimo una volta al giorno."""
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

Stato = Callable[[str], None]
Progresso = Callable[[Optional[float]], None]  # frazione 0-1 oppure None (indeterminato)

URL_YTDLP = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
URL_FFMPEG = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
]
NO_FINESTRA = 0x08000000  # CREATE_NO_WINDOW: niente finestre nere della console


def _funziona(exe: Path, arg: str) -> bool:
    if not exe.exists() or exe.stat().st_size < 100_000:
        return False
    try:
        p = subprocess.run([str(exe), arg], capture_output=True, timeout=30, creationflags=NO_FINESTRA)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return p.returncode == 0


def scarica(url: str, dest: Path, stato: Stato, progresso: Progresso, etichetta: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    parziale = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "EserciziCanzone"})
    with urllib.request.urlopen(req, timeout=60) as r, parziale.open("wb") as f:
        totale = int(r.headers.get("Content-Length") or 0)
        letti = 0
        ultimo = 0.0
        while True:
            blocco = r.read(256 * 1024)
            if not blocco:
                break
            f.write(blocco)
            letti += len(blocco)
            if time.time() - ultimo > 0.2:
                ultimo = time.time()
                if totale:
                    stato(f"Scarico {etichetta}: {letti / 1e6:.0f} di {totale / 1e6:.0f} MB")
                    progresso(letti / totale)
                else:
                    stato(f"Scarico {etichetta}: {letti / 1e6:.0f} MB")
                    progresso(None)
    parziale.replace(dest)
    progresso(None)


def assicura_ytdlp(bin_dir: Path, stato: Stato, progresso: Progresso) -> Path:
    exe = bin_dir / "yt-dlp.exe"
    if _funziona(exe, "--version"):
        return exe
    stato("Scarico yt-dlp (serve per leggere i video di YouTube)")
    scarica(URL_YTDLP, exe, stato, progresso, "yt-dlp")
    if not _funziona(exe, "--version"):
        raise RuntimeError("yt-dlp scaricato ma non funziona (forse bloccato dall'antivirus).")
    return exe


def aggiorna_ytdlp(exe: Path, stato: Stato, registro: Callable[[str], None]) -> None:
    """yt-dlp -U al massimo una volta al giorno: YouTube cambia spesso e questo è il pezzo che si rompe."""
    marcatore = exe.parent / "ytdlp_ultimo_aggiornamento.txt"
    if marcatore.exists() and time.time() - marcatore.stat().st_mtime < 86400:
        return
    stato("Controllo aggiornamenti di yt-dlp")
    try:
        p = subprocess.run([str(exe), "-U"], capture_output=True, text=True, timeout=180, creationflags=NO_FINESTRA)
        registro(f"yt-dlp -U: {(p.stdout or '').strip()[-300:]} {(p.stderr or '').strip()[-300:]}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        registro(f"yt-dlp -U non riuscito: {exc}")
    marcatore.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")


def assicura_ffmpeg(bin_dir: Path, stato: Stato, progresso: Progresso) -> Path:
    exe = bin_dir / "ffmpeg.exe"
    if _funziona(exe, "-version"):
        return exe
    ultimo_errore = None
    for url in URL_FFMPEG:
        zip_path = bin_dir / "ffmpeg.zip"
        try:
            stato("Scarico ffmpeg (serve per i fotogrammi, solo la prima volta)")
            scarica(url, zip_path, stato, progresso, "ffmpeg")
            stato("Estraggo ffmpeg")
            with zipfile.ZipFile(zip_path) as z:
                membro = next((m for m in z.namelist() if m.lower().endswith("/bin/ffmpeg.exe") or m.lower().endswith("ffmpeg.exe")), None)
                if membro is None:
                    raise RuntimeError("ffmpeg.exe non trovato nello zip")
                with z.open(membro) as src, exe.open("wb") as dst:
                    while True:
                        blocco = src.read(1024 * 1024)
                        if not blocco:
                            break
                        dst.write(blocco)
            zip_path.unlink(missing_ok=True)
            if _funziona(exe, "-version"):
                return exe
            ultimo_errore = "ffmpeg scaricato ma non funziona"
        except Exception as exc:  # prova l'URL successivo
            ultimo_errore = str(exc)
            zip_path.unlink(missing_ok=True)
    raise RuntimeError(f"Impossibile scaricare ffmpeg: {ultimo_errore}")
