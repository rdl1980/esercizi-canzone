"""Avvio dell'app locale "Esercizi canzone" (Windows).

Finestra di stato con tkinter; in sequenza: aggiornamento da GitHub, ffmpeg e yt-dlp, server locale, browser.
Dati in %LOCALAPPDATA%\\EserciziCanzone, PDF copiati anche in Documenti\\Esercizi canzone.
"""
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BASE_APP = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    CARTELLA_INSTALLAZIONE = Path(sys.executable).resolve().parent
else:
    BASE_APP = Path(__file__).resolve().parent.parent  # cartella webapp/
    CARTELLA_INSTALLAZIONE = BASE_APP
    sys.path.insert(0, str(BASE_APP))

from app.versione import NOME_APP, VERSIONE  # noqa: E402

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NOME_APP
BIN_DIR = CONFIG_DIR / "bin"
DATA_DIR = CONFIG_DIR / "data"
LOG_PATH = CONFIG_DIR / "avvio.log"
PORTA_PREFERITA = 8765


def cartella_documenti() -> Path:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            valore, _ = winreg.QueryValueEx(k, "Personal")
            return Path(os.path.expandvars(valore))
    except OSError:
        return Path.home() / "Documents"


CARTELLA_PDF = cartella_documenti() / "Esercizi canzone"


def registro(msg: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def porta_libera() -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORTA_PREFERITA))
            return PORTA_PREFERITA
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def app_gia_aperta() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA_PREFERITA}/api/versione", timeout=1.5) as r:
            import json

            return json.loads(r.read().decode("utf-8")).get("app") == "esercizi-canzone"
    except Exception:
        return False


class Finestra:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title(f"Esercizi canzone {VERSIONE}")
        self.root.geometry("460x240")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.chiudi)
        cornice = ttk.Frame(self.root, padding=16)
        cornice.pack(fill="both", expand=True)
        ttk.Label(cornice, text="Esercizi canzone", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.stato_var = tk.StringVar(value="Avvio…")
        ttk.Label(cornice, textvariable=self.stato_var, wraplength=420, justify="left").pack(anchor="w", pady=(8, 4))
        self.barra = ttk.Progressbar(cornice, mode="indeterminate", length=420)
        self.barra.pack(anchor="w", pady=(0, 10))
        self.barra.start(12)
        bottoni = ttk.Frame(cornice)
        bottoni.pack(anchor="w", pady=(4, 0))
        self.btn_apri = ttk.Button(bottoni, text="Apri nel browser", command=self.apri_browser, state="disabled")
        self.btn_apri.pack(side="left")
        ttk.Button(bottoni, text="Cartella dei PDF", command=self.apri_cartella_pdf).pack(side="left", padx=6)
        ttk.Button(bottoni, text="Esci", command=self.chiudi).pack(side="left")
        ttk.Label(cornice, text="Lascia aperta questa finestra mentre usi il sito.", foreground="#666").pack(anchor="w", pady=(12, 0))
        self.url = ""
        self.server = None
        self.chiusura = False

    # chiamabili da altri thread
    def stato(self, testo: str) -> None:
        if not re.match(r"^Scarico .*: \d+ (di \d+ MB|MB)$", testo):  # niente righe di avanzamento nel log
            registro(testo)
        self.root.after(0, self.stato_var.set, testo)

    def progresso(self, frazione) -> None:
        def _agg():
            if frazione is None:
                if self.barra["mode"] != "indeterminate":
                    self.barra.configure(mode="indeterminate")
                    self.barra.start(12)
            else:
                if self.barra["mode"] != "determinate":
                    self.barra.stop()
                    self.barra.configure(mode="determinate", maximum=100)
                self.barra["value"] = frazione * 100
        self.root.after(0, _agg)

    def pronto(self, url: str) -> None:
        def _agg():
            self.url = url
            self.barra.stop()
            self.barra.configure(mode="determinate", maximum=100)
            self.barra["value"] = 100
            self.btn_apri.configure(state="normal")
            self.stato_var.set(f"Pronto: il sito è aperto nel browser ({url}).")
        self.root.after(0, _agg)

    def errore(self, testo: str) -> None:
        def _agg():
            self.barra.stop()
            self.stato_var.set("Errore: " + testo)
        self.root.after(0, _agg)

    def apri_browser(self) -> None:
        if self.url:
            webbrowser.open(self.url)

    def apri_cartella_pdf(self) -> None:
        CARTELLA_PDF.mkdir(parents=True, exist_ok=True)
        os.startfile(str(CARTELLA_PDF))  # type: ignore[attr-defined]

    def chiudi(self) -> None:
        if self.chiusura:
            return
        self.chiusura = True
        self.stato_var.set("Chiusura…")
        if self.server is not None:
            self.server.should_exit = True
        self.root.after(800, lambda: os._exit(0))

    def esegui(self) -> None:
        self.root.mainloop()


def prepara(fin: Finestra) -> None:
    """Thread di preparazione: aggiornamento, strumenti, server."""
    try:
        from desktop import aggiornamenti, strumenti

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if "--aggiornato" in sys.argv:
            fin.stato(f"Aggiornato alla versione {VERSIONE}")
            time.sleep(1.5)

        # 1. aggiornamento dell'app
        try:
            remota = aggiornamenti.aggiornamento_disponibile(fin.stato)
            if remota and aggiornamenti.scarica_e_applica(remota, CONFIG_DIR, CARTELLA_INSTALLAZIONE,
                                                           fin.stato, fin.progresso, registro):
                fin.stato(f"Installo la versione {remota['tag']}: l'app si riavvia da sola tra qualche secondo")
                time.sleep(1.0)
                os._exit(0)
        except Exception as exc:  # un aggiornamento fallito non deve bloccare l'app
            registro("aggiornamento non riuscito: " + traceback.format_exc())
            fin.stato(f"Aggiornamento non riuscito ({exc}); continuo con la versione {VERSIONE}")
            time.sleep(1.5)

        # 2. strumenti esterni
        ffmpeg = strumenti.assicura_ffmpeg(BIN_DIR, fin.stato, fin.progresso)
        ytdlp = strumenti.assicura_ytdlp(BIN_DIR, fin.stato, fin.progresso)
        strumenti.aggiorna_ytdlp(ytdlp, fin.stato, registro)

        # 3. ambiente per la webapp (prima di importarla)
        global CARTELLA_PDF
        try:
            CARTELLA_PDF.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # Documenti non scrivibile (protezione cartelle, OneDrive...): ripiego
            registro(f"cartella {CARTELLA_PDF} non utilizzabile ({exc}): uso {CONFIG_DIR / 'pdf'}")
            CARTELLA_PDF = CONFIG_DIR / "pdf"
            CARTELLA_PDF.mkdir(parents=True, exist_ok=True)
        os.environ.update({
            "MODALITA_LOCALE": "1",
            "DATA_DIR": str(DATA_DIR),
            "FFMPEG_BIN": str(ffmpeg),
            "YTDLP_BIN": str(ytdlp),
            "ESPORTA_PDF_DIR": str(CARTELLA_PDF),
            "YTDLP_REMOTE_COMPONENTS": "false",
        })
        fin.stato("Avvio il sito locale")
        import uvicorn

        from app.main import app as webapp

        porta = porta_libera()
        config = uvicorn.Config(webapp, host="127.0.0.1", port=porta, log_level="warning", log_config=None)
        fin.server = uvicorn.Server(config)
        threading.Thread(target=fin.server.run, name="uvicorn", daemon=True).start()
        for _ in range(100):
            if fin.server.started:
                break
            time.sleep(0.1)
        url = f"http://127.0.0.1:{porta}/"
        webbrowser.open(url)
        fin.pronto(url)
    except Exception as exc:
        registro("errore di avvio: " + traceback.format_exc())
        fin.errore(f"{exc}\n(dettagli in {LOG_PATH})")


def main() -> None:
    registro(f"--- avvio {NOME_APP} {VERSIONE} ({'exe' if FROZEN else 'sorgenti'}) ---")
    if app_gia_aperta():
        webbrowser.open(f"http://127.0.0.1:{PORTA_PREFERITA}/")
        return
    fin = Finestra()
    threading.Thread(target=prepara, args=(fin,), name="preparazione", daemon=True).start()
    fin.esegui()


if __name__ == "__main__":
    main()
