"""Orchestrazione della generazione di un esercizio (eseguita dal worker)."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..config import DURATA_MAX_VIDEO, ESERCIZI_DIR, ESPORTA_PDF_DIR, INTERVALLO_FOTOGRAMMI
from . import ai, frames, layout, lyrics, pdf, youtube

Avanzamento = Callable[[str, int], None]


def cartella_esercizio(esercizio_id: int) -> Path:
    return ESERCIZI_DIR / str(esercizio_id)


def _logger(cartella: Path) -> Callable[[str], None]:
    cartella.mkdir(parents=True, exist_ok=True)
    f = cartella / "log.txt"

    def log(msg: str) -> None:
        with f.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")

    return log


def genera(esercizio: dict, avanzamento: Avanzamento) -> dict:
    """Esegue tutta la pipeline; restituisce i campi da salvare sulla riga esercizio."""
    eid = esercizio["id"]
    cartella = cartella_esercizio(eid)
    cartella.mkdir(parents=True, exist_ok=True)
    log = _logger(cartella)
    log(f"--- generazione esercizio {eid} ({esercizio['url']}) ---")
    for vecchio in ("esercizio.pdf", "anteprima.png", "esercizio.json"):
        (cartella / vecchio).unlink(missing_ok=True)

    # 1. informazioni sul video
    avanzamento("Controllo il video su YouTube", 3)
    url = youtube.url_canonico(esercizio["video_id"])
    info = youtube.info_video(url)
    if info["is_live"]:
        raise youtube.VideoNonDisponibile("Il link è una diretta: serve un video registrato.")
    if info["durata"] <= 0:
        raise youtube.VideoNonDisponibile("Impossibile leggere la durata del video.")
    if info["durata"] > DURATA_MAX_VIDEO:
        raise youtube.VideoNonDisponibile(
            f"Il video dura {int(info['durata'] // 60)} minuti: il massimo consentito è {DURATA_MAX_VIDEO // 60} minuti.")
    titolo_video = info["titolo"] or esercizio["video_id"]
    titolo_canzone = lyrics.pulisci_titolo_video(titolo_video, info.get("canale", "")) or titolo_video
    log(f"video: {titolo_video} ({info['durata']:.0f}s) -> titolo canzone: {titolo_canzone}")

    # 2. download (riutilizzato se già presente per lo stesso video)
    cartella_video = cartella / "video"
    marcatore = cartella_video / "video_id.txt"
    video = youtube._trova_video(cartella_video) if cartella_video.exists() else None
    if video is None or not marcatore.exists() or marcatore.read_text(encoding="utf-8").strip() != esercizio["video_id"]:
        avanzamento("Scarico il video", 8)
        shutil.rmtree(cartella_video, ignore_errors=True)
        video = youtube.scarica_video(url, cartella_video, log)
        marcatore.write_text(esercizio["video_id"], encoding="utf-8")
        shutil.rmtree(cartella / "frames", ignore_errors=True)
        shutil.rmtree(cartella / "fogli", ignore_errors=True)
    else:
        log("video già scaricato, lo riutilizzo")
    sottotitoli = youtube.leggi_sottotitoli(cartella_video)
    if sottotitoli:
        (cartella / "sottotitoli.txt").write_text(sottotitoli, encoding="utf-8")
        log("sottotitoli italiani trovati")

    # 3. fotogrammi + fogli di contatto
    avanzamento("Estraggo i fotogrammi", 20)

    def prog_frame(fatti: int, totale: int) -> None:
        avanzamento(f"Estraggo i fotogrammi ({fatti}/{totale})", 20 + int(20 * fatti / max(totale, 1)))

    lista_frames = frames.estrai_tutti(video, info["durata"], INTERVALLO_FOTOGRAMMI, cartella / "frames", prog_frame)
    avanzamento("Preparo i fogli di contatto", 42)
    fogli = frames.fogli_contatto(lista_frames, cartella / "fogli")
    tempi_validi = [f["t"] for f in lista_frames]
    log(f"{len(lista_frames)} fotogrammi, {len(fogli)} fogli")

    # 4. testo
    avanzamento("Preparo il testo", 45)
    blocchi = lyrics.prepara_testo(esercizio["testo"], esercizio["modalita"])
    righe = lyrics.righe_piatte(blocchi)
    if len(righe) < 1:
        raise RuntimeError("Il testo della canzone è vuoto dopo la pulizia.")
    titolo = " ".join((esercizio.get("titolo") or "").split()) or titolo_canzone

    # 5. scelta delle parole con l'AI
    avanzamento("Scelgo le parole e le immagini con l'AI", 50)
    selezioni = ai.scegli_parole(righe, int(esercizio["n_parole"] or 0), fogli, titolo, tempi_validi, log)
    if not selezioni:
        raise ai.ErroreAI("L'AI non ha trovato parole rappresentabili con immagini del video: prova con un altro testo.")
    log("selezioni: " + json.dumps(selezioni, ensure_ascii=False))

    # 6. estrazione dei singoli fotogrammi e verifica
    cartella_img = cartella / "immagini"
    shutil.rmtree(cartella_img, ignore_errors=True)
    cartella_img.mkdir()

    def estrai_per(selez: list[dict], suffisso: str) -> list[Path]:
        uscite = []
        for i, s in enumerate(selez):
            nome = f"{i:02d}_{ai.pulisci_nome_file(s['parola'])}{suffisso}.jpg"
            dest = cartella_img / nome
            if not frames.estrai_fotogramma(video, s["timestamp"], dest, larghezza=800):
                # ripiego sul fotogramma già estratto a bassa risoluzione
                vicino = min(lista_frames, key=lambda f: abs(f["t"] - s["timestamp"]))
                shutil.copy(vicino["file"], dest)
            uscite.append(dest)
        return uscite

    avanzamento("Estraggo le immagini scelte", 70)
    immagini = estrai_per(selezioni, "")
    avanzamento("Verifico le immagini con l'AI", 75)
    verificate = ai.verifica_fotogrammi(selezioni, immagini, fogli, tempi_validi, log)
    da_rifare = [i for i, s in enumerate(verificate) if not s.get("verificata")]
    if da_rifare:
        avanzamento("Sostituisco le immagini scartate", 85)
        for i in da_rifare:
            nuova = cartella_img / f"{i:02d}_{ai.pulisci_nome_file(verificate[i]['parola'])}.jpg"
            if not frames.estrai_fotogramma(video, verificate[i]["timestamp"], nuova, larghezza=800):
                log(f"estrazione alternativa fallita per {verificate[i]['parola']}")
            immagini[i] = nuova
    selezioni = verificate
    log("immagini pronte")

    # 7. esercizio.json + PDF
    avanzamento("Impagino il PDF", 90)
    mappa_img = {i: f"immagini/{p.name}" for i, p in enumerate(immagini) if p.exists()}
    spec = {
        "titolo": titolo,
        "font_size": 28,
        "img_height_cm": 3.0,
        "video": url,
        "parole": [{"parola": s["parola"], "riga": s["riga"], "timestamp": s["timestamp"]} for s in selezioni],
        "righe": layout.costruisci_righe(blocchi, selezioni, mappa_img),
    }
    spec_path = cartella / "esercizio.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    log("esercizio.json scritto")
    pdf_path = pdf.crea_pdf(spec_path, cartella / "esercizio.pdf")
    log("PDF creato")
    pdf.anteprima_png(pdf_path, cartella / "anteprima.png")
    log("anteprima creata")
    if ESPORTA_PDF_DIR:
        try:
            ESPORTA_PDF_DIR.mkdir(parents=True, exist_ok=True)
            nome = "".join(c if c.isalnum() or c in " -_'" else "_" for c in titolo).strip() or "esercizio"
            shutil.copy(pdf_path, ESPORTA_PDF_DIR / f"{nome}.pdf")
            log(f"PDF copiato in {ESPORTA_PDF_DIR}")
        except OSError as exc:
            log(f"copia del PDF in {ESPORTA_PDF_DIR} non riuscita: {exc}")
    # `titolo` (scelta dell'utente) non viene toccato: se è vuoto il titolo mostrato resta quello della canzone
    return {
        "titolo_video": titolo_video,
        "titolo_canzone": titolo_canzone,
        "durata_video": info["durata"],
        "parole": json.dumps([s["parola"] for s in selezioni], ensure_ascii=False),
    }
