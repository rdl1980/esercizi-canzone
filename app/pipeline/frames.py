"""Estrazione dei fotogrammi con ffmpeg e composizione dei fogli di contatto."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from ..config import FFMPEG_BIN

LARGHEZZA_FRAME = 640


def estrai_fotogramma(video: Path, secondi: float, uscita: Path, larghezza: int = LARGHEZZA_FRAME) -> bool:
    """Un solo fotogramma all'istante indicato. `-ss` prima di `-i`: il filtro fps= dava tempi sbagliati."""
    uscita.parent.mkdir(parents=True, exist_ok=True)
    args = [
        FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{secondi:.3f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "3", "-vf", f"scale={larghezza}:-2", str(uscita),
    ]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return p.returncode == 0 and uscita.exists() and uscita.stat().st_size > 0


def nome_frame(secondi: float) -> str:
    return f"f_{secondi:07.1f}.jpg".replace(".", "_", 1).replace("_jpg", ".jpg")


def estrai_tutti(video: Path, durata: float, intervallo: float, cartella: Path,
                 avanzamento: Callable[[int, int], None] | None = None) -> list[dict]:
    """Un fotogramma ogni `intervallo` secondi. Restituisce [{"t": secondi, "file": percorso}]."""
    cartella.mkdir(parents=True, exist_ok=True)
    manifest = cartella / "manifest.json"
    if manifest.exists():
        try:
            dati = json.loads(manifest.read_text(encoding="utf-8"))
            if dati.get("intervallo") == intervallo and all(Path(f["file"]).exists() for f in dati["frames"]):
                return dati["frames"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    tempi = []
    t = 0.5
    while t < max(durata - 0.5, 1.0):
        tempi.append(round(t, 1))
        t += intervallo
    risultati: list[dict] = []
    fatti = 0

    def lavoro(sec: float):
        f = cartella / f"f_{int(sec * 10):06d}.jpg"
        ok = estrai_fotogramma(video, sec, f)
        return sec, f, ok

    with ThreadPoolExecutor(max_workers=4) as pool:
        for sec, f, ok in pool.map(lavoro, tempi):
            fatti += 1
            if ok:
                risultati.append({"t": sec, "file": str(f)})
            if avanzamento and fatti % 10 == 0:
                avanzamento(fatti, len(tempi))
    if not risultati:
        raise RuntimeError("ffmpeg non è riuscito a estrarre i fotogrammi dal video.")
    manifest.write_text(json.dumps({"intervallo": intervallo, "frames": risultati}), encoding="utf-8")
    return risultati


def etichetta_tempo(secondi: float) -> str:
    return f"{secondi:.1f}s"


def fogli_contatto(frames: list[dict], cartella: Path, colonne: int = 5, righe: int = 4,
                   larghezza_min: int = 300) -> list[Path]:
    """Griglie di miniature con il tempo stampato sopra ciascuna (scritto con Pillow, non con drawtext)."""
    cartella.mkdir(parents=True, exist_ok=True)
    for vecchio in cartella.glob("foglio_*.jpg"):
        vecchio.unlink()
    per_foglio = colonne * righe
    font = ImageFont.load_default(size=22)
    fogli: list[Path] = []
    alt_etichetta = 30
    margine = 6
    for n, inizio in enumerate(range(0, len(frames), per_foglio), 1):
        gruppo = frames[inizio:inizio + per_foglio]
        prima = Image.open(gruppo[0]["file"])
        rapporto = prima.height / prima.width
        prima.close()
        w = larghezza_min
        h = int(w * rapporto)
        cella_h = h + alt_etichetta
        n_righe = (len(gruppo) + colonne - 1) // colonne
        foglio = Image.new("RGB", (colonne * (w + margine) + margine, n_righe * (cella_h + margine) + margine), "white")
        draw = ImageDraw.Draw(foglio)
        for i, fr in enumerate(gruppo):
            r, c = divmod(i, colonne)
            x = margine + c * (w + margine)
            y = margine + r * (cella_h + margine)
            draw.rectangle([x, y, x + w, y + alt_etichetta - 2], fill="black")
            draw.text((x + 6, y + 3), etichetta_tempo(fr["t"]), fill="yellow", font=font)
            with Image.open(fr["file"]) as im:
                im = im.convert("RGB").resize((w, h))
                foglio.paste(im, (x, y + alt_etichetta))
        percorso = cartella / f"foglio_{n:02d}.jpg"
        foglio.save(percorso, "JPEG", quality=85)
        fogli.append(percorso)
    return fogli
