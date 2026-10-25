"""Coda dei lavori di generazione: un thread lavoratore elabora un esercizio alla volta."""
import logging
import queue
import shutil
import threading
import traceback

from .db import adesso, aggiorna_esercizio, db

log = logging.getLogger("esercizi.jobs")
_coda: "queue.Queue[int]" = queue.Queue()
_thread: threading.Thread | None = None

STATI = ("coda", "in_lavorazione", "pronto", "errore")


def accoda(esercizio_id: int) -> None:
    aggiorna_esercizio(esercizio_id, stato="coda", fase="In attesa", progresso=0, errore=None)
    _coda.put(esercizio_id)


def _lavora(esercizio_id: int) -> None:
    from .pipeline.run import genera  # import tardivo: la pipeline carica librerie pesanti

    with db() as conn:
        riga = conn.execute("SELECT * FROM esercizi WHERE id = ?", (esercizio_id,)).fetchone()
    if riga is None:
        return
    aggiorna_esercizio(esercizio_id, stato="in_lavorazione", fase="Avvio", progresso=1, errore=None)

    def avanzamento(fase: str, progresso: int) -> None:
        aggiorna_esercizio(esercizio_id, fase=fase, progresso=progresso)

    try:
        risultato = genera(dict(riga), avanzamento)
    except Exception as exc:  # qualunque errore finisce nello stato dell'esercizio
        log.error("Esercizio %s fallito: %s\n%s", esercizio_id, exc, traceback.format_exc())
        messaggio = str(exc) or exc.__class__.__name__
        aggiorna_esercizio(esercizio_id, stato="errore", fase="Errore", errore=messaggio[:1000])
        _pulisci_se_eliminato(esercizio_id)
        return
    if _pulisci_se_eliminato(esercizio_id):
        return
    aggiorna_esercizio(
        esercizio_id,
        stato="pronto",
        fase="Pronto",
        progresso=100,
        errore=None,
        completato_il=adesso(),
        **risultato,
    )


def _pulisci_se_eliminato(esercizio_id: int) -> bool:
    """Se l'esercizio è stato eliminato mentre era in coda, rimuove i file che la pipeline può aver creato."""
    with db() as conn:
        esiste = conn.execute("SELECT 1 FROM esercizi WHERE id = ?", (esercizio_id,)).fetchone()
    if esiste:
        return False
    from .pipeline.run import cartella_esercizio

    shutil.rmtree(cartella_esercizio(esercizio_id), ignore_errors=True)
    return True


def _ciclo() -> None:
    while True:
        esercizio_id = _coda.get()
        try:
            _lavora(esercizio_id)
        except Exception:  # non deve mai fermare il thread
            log.exception("Errore inatteso nel worker")
        finally:
            _coda.task_done()


def avvia_worker() -> None:
    """Avvia il thread e rimette in coda i lavori rimasti dal precedente avvio."""
    global _thread
    if _thread is not None:
        return
    with db() as conn:
        conn.execute(
            "UPDATE esercizi SET stato='errore', fase='Errore', errore=? WHERE stato='in_lavorazione'",
            ("Generazione interrotta dal riavvio del server: premi Rigenera.",),
        )
        in_coda = [r["id"] for r in conn.execute("SELECT id FROM esercizi WHERE stato='coda' ORDER BY id")]
    for eid in in_coda:
        _coda.put(eid)
    _thread = threading.Thread(target=_ciclo, name="worker-esercizi", daemon=True)
    _thread.start()
