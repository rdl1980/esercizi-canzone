"""Aggiornamento automatico dell'app locale dalle GitHub Releases.

A ogni avvio: legge l'ultima release, se è più nuova scarica lo zip, lo estrae e lancia uno script
che aspetta la chiusura dell'app, copia i nuovi file sopra i vecchi e riavvia l'app.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from app.versione import ASSET_WINDOWS, NOME_APP, REPO_GITHUB, VERSIONE

Stato = Callable[[str], None]
Progresso = Callable[[Optional[float]], None]
API_RELEASE = f"https://api.github.com/repos/{REPO_GITHUB}/releases/latest"


def _numero(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def versione_remota(timeout: float = 8.0) -> Optional[dict]:
    """{'tag', 'url', 'dimensione', 'note'} dell'ultima release, None se non raggiungibile o senza release."""
    req = urllib.request.Request(API_RELEASE, headers={"Accept": "application/vnd.github+json", "User-Agent": NOME_APP})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dati = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    asset = next((a for a in dati.get("assets", []) if a.get("name") == ASSET_WINDOWS), None)
    if not asset:
        return None
    return {"tag": dati.get("tag_name", ""), "url": asset["browser_download_url"],
            "dimensione": int(asset.get("size") or 0), "note": (dati.get("body") or "")[:500]}


def aggiornamento_disponibile(stato: Stato) -> Optional[dict]:
    stato("Controllo se c'è una versione nuova")
    remota = versione_remota()
    if remota and _numero(remota["tag"]) > _numero(VERSIONE):
        return remota
    return None


def _scarica(url: str, dest: Path, dimensione: int, stato: Stato, progresso: Progresso) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": NOME_APP})
    parziale = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=60) as r, parziale.open("wb") as f:
        totale = int(r.headers.get("Content-Length") or dimensione or 0)
        letti = 0
        while True:
            blocco = r.read(256 * 1024)
            if not blocco:
                break
            f.write(blocco)
            letti += len(blocco)
            if totale:
                stato(f"Scarico l'aggiornamento: {letti / 1e6:.0f} di {totale / 1e6:.0f} MB")
                progresso(letti / totale)
    parziale.replace(dest)


def _cartella_con_exe(radice: Path) -> Optional[Path]:
    if (radice / f"{NOME_APP}.exe").exists():
        return radice
    for figlia in radice.iterdir():
        if figlia.is_dir() and (figlia / f"{NOME_APP}.exe").exists():
            return figlia
    return None


def scarica_e_applica(remota: dict, cartella_lavoro: Path, cartella_installazione: Path,
                      stato: Stato, progresso: Progresso, registro: Callable[[str], None]) -> bool:
    """Scarica lo zip e avvia lo script di sostituzione. Se restituisce True l'app deve chiudersi subito."""
    if not getattr(sys, "frozen", False):
        registro(f"versione {remota['tag']} disponibile ma l'app non è impacchettata: aggiornamento saltato")
        return False
    if not os.access(cartella_installazione, os.W_OK):
        registro(f"cartella {cartella_installazione} non scrivibile: aggiornamento saltato")
        stato(f"Nuova versione {remota['tag']} disponibile, ma la cartella dell'app non è scrivibile")
        return False
    lavoro = cartella_lavoro / "aggiornamento"
    shutil.rmtree(lavoro, ignore_errors=True)
    lavoro.mkdir(parents=True, exist_ok=True)
    zip_path = lavoro / ASSET_WINDOWS
    stato(f"Scarico la versione {remota['tag']}")
    _scarica(remota["url"], zip_path, remota["dimensione"], stato, progresso)
    progresso(None)
    stato("Preparo l'aggiornamento")
    nuovo = lavoro / "nuovo"
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(nuovo)
    zip_path.unlink(missing_ok=True)
    sorgente = _cartella_con_exe(nuovo)
    if sorgente is None:
        raise RuntimeError("lo zip dell'aggiornamento non contiene l'app")
    log = cartella_lavoro / "aggiornamento.log"
    script = lavoro / "aggiorna.cmd"
    script.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "PID={os.getpid()}"\r\n'
        f'set "NUOVO={sorgente}"\r\n'
        f'set "DEST={cartella_installazione}"\r\n'
        f'set "LOG={log}"\r\n'
        f"echo [%date% %time%] aggiornamento a {remota['tag']} >> \"%LOG%\"\r\n"
        ":attesa\r\n"
        'tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul\r\n'
        "if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto attesa )\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        'robocopy "%NUOVO%" "%DEST%" /E /R:10 /W:1 /NFL /NDL /NJH >> "%LOG%" 2>&1\r\n'
        "if %ERRORLEVEL% GEQ 8 ( echo copia non riuscita >> \"%LOG%\" )\r\n"
        f'start "" "%DEST%\\{NOME_APP}.exe" --aggiornato\r\n'
        'rmdir /s /q "%NUOVO%" >nul 2>&1\r\n'
        "endlocal\r\n",
        encoding="utf-8",
    )
    DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(["cmd.exe", "/c", str(script)], cwd=str(lavoro), creationflags=DETACHED, close_fds=True)
    registro(f"script di aggiornamento avviato per {remota['tag']}")
    return True
