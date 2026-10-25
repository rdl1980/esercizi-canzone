"""Impaginazione del PDF A4 con reportlab a partire da esercizio.json."""
import json
import re
from pathlib import Path

import pymupdf  # importato qui (thread principale): dentro il thread del worker l'import impiega ~15 s
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_FONT_CANDIDATI = [
    ("Arial", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("Arial", "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf", "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
    ("LiberationSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("LiberationSans", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_font_cache: tuple[str, str] | None = None


def carica_font() -> tuple[str, str]:
    """(normale, grassetto): Arial se c'è, altrimenti un equivalente, altrimenti Helvetica."""
    global _font_cache
    if _font_cache:
        return _font_cache
    for nome, reg, bold in _FONT_CANDIDATI:
        if Path(reg).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont(nome, reg))
                pdfmetrics.registerFont(TTFont(nome + "-Bold", bold))
                _font_cache = (nome, nome + "-Bold")
                return _font_cache
            except Exception:
                continue
    _font_cache = ("Helvetica", "Helvetica-Bold")
    return _font_cache


class Impaginatore:
    def __init__(self, spec: dict, base: Path, uscita: Path):
        self.spec = spec
        self.base = base
        self.uscita = uscita
        self.font, self.font_bold = carica_font()
        self.corpo = float(spec.get("font_size", 28))
        self.interlinea = self.corpo * 1.3
        self.img_h = float(spec.get("img_height_cm", 3.0)) * cm
        self.margine = 1.5 * cm
        self.larghezza_pag, self.altezza_pag = A4
        self.larghezza_utile = self.larghezza_pag - 2 * self.margine
        self.spazio_immagine = 16  # spazio orizzontale attorno a un'immagine
        self.distanza_trattini = 0.55 * cm  # tra il fondo dell'immagine e i trattini
        self.canvas = canvas.Canvas(str(uscita), pagesize=A4)
        self.canvas.setTitle(spec.get("titolo", "Esercizio"))
        self.y = self.altezza_pag - self.margine

    # --- misure -------------------------------------------------------------
    def larghezza_testo(self, testo: str, font: str | None = None, corpo: float | None = None) -> float:
        return pdfmetrics.stringWidth(testo, font or self.font, corpo or self.corpo)

    def atomi(self, riga: list) -> list[dict]:
        """Spezza la riga in parole e immagini, ognuna con la sua larghezza."""
        atomi: list[dict] = []
        for pezzo in riga:
            if isinstance(pezzo, str):
                for m in re.finditer(r"\S+\s*", pezzo):
                    tok = m.group(0)
                    parola = tok.rstrip()
                    atomi.append({"tipo": "testo", "testo": parola,
                                  "larghezza": self.larghezza_testo(parola),
                                  "larghezza_con_spazio": self.larghezza_testo(tok),
                                  "spazio_dopo": tok != parola})
            else:
                percorso = self.base / pezzo["img"]
                with Image.open(percorso) as im:
                    w, h = im.size
                img_w = self.img_h * w / h
                trattini = " ".join("_" * len(pezzo["parola"]))
                tratt_w = self.larghezza_testo(trattini)
                larghezza = max(img_w, tratt_w) + self.spazio_immagine
                atomi.append({"tipo": "img", "percorso": str(percorso), "img_w": img_w, "trattini": trattini,
                              "larghezza": larghezza, "larghezza_con_spazio": larghezza, "spazio_dopo": True})
        return atomi

    def _larghezza_riga(self, atomi: list[dict]) -> float:
        if not atomi:
            return 0.0
        return sum(a["larghezza_con_spazio"] for a in atomi[:-1]) + atomi[-1]["larghezza"]

    def dividi_in_righe(self, atomi: list[dict]) -> list[list[dict]]:
        """Va a capo quando serve, ma un'immagine porta con sé le 1-2 parole che la precedono
        e l'ultima riga non resta con una parola sola."""
        righe: list[list[dict]] = []
        corrente: list[dict] = []
        for a in atomi:
            if corrente and self._larghezza_riga(corrente + [a]) > self.larghezza_utile:
                trascina: list[dict] = []
                if a["tipo"] == "img":
                    # porta a capo fino a 2 parole di testo (senza spezzare dopo una virgola)
                    while corrente and len(trascina) < 2 and corrente[-1]["tipo"] == "testo" \
                            and not corrente[-1]["testo"].endswith((",", ".", ";", ":", "!", "?")):
                        trascina.insert(0, corrente.pop())
                    if not corrente:  # non c'era spazio comunque: lascia tutto com'era
                        corrente, trascina = trascina, []
                righe.append(corrente)
                corrente = trascina
            corrente.append(a)
        if corrente:
            righe.append(corrente)
        # evita l'ultima riga con una parola sola
        if len(righe) >= 2 and len(righe[-1]) == 1 and righe[-1][0]["tipo"] == "testo" and len(righe[-2]) >= 3:
            candidato = righe[-2][-1]
            if candidato["tipo"] == "testo" and self._larghezza_riga([candidato] + righe[-1]) <= self.larghezza_utile:
                righe[-1].insert(0, righe[-2].pop())
        return righe

    # --- disegno --------------------------------------------------------------
    def nuova_pagina(self) -> None:
        self.canvas.showPage()
        self.y = self.altezza_pag - self.margine

    def _spezza_titolo(self, testo: str, corpo: float) -> list[str]:
        righe: list[str] = []
        corrente = ""
        for parola in testo.split():
            prova = f"{corrente} {parola}".strip()
            if corrente and self.larghezza_testo(prova, self.font_bold, corpo) > self.larghezza_utile:
                righe.append(corrente)
                corrente = parola
            else:
                corrente = prova
        if corrente:
            righe.append(corrente)
        return righe

    def titolo(self, testo: str) -> None:
        """Titolo centrato in maiuscolo: va a capo se non entra e, oltre due righe, riduce il corpo. Mai tagliato."""
        testo = " ".join(testo.split()).upper()
        corpo = self.corpo + 4
        righe = self._spezza_titolo(testo, corpo)
        while len(righe) > 2 and corpo > 16:
            corpo -= 2
            righe = self._spezza_titolo(testo, corpo)
        self.canvas.setFont(self.font_bold, corpo)
        for riga in righe:
            self.y -= corpo
            self.canvas.drawCentredString(self.larghezza_pag / 2, self.y, riga)
            self.y -= corpo * 0.25
        self.y -= corpo * 0.65

    def riga_visiva(self, atomi: list[dict]) -> None:
        con_img = any(a["tipo"] == "img" for a in atomi)
        sopra = self.img_h + 2 if con_img else self.corpo * 0.85  # altezza sopra la linea di base
        sotto = (self.distanza_trattini + self.corpo * 0.75) if con_img else self.corpo * 0.3
        spazio_dopo = self.corpo * 0.45 if con_img else self.corpo * 0.25
        if self.y - (sopra + sotto) < self.margine:
            self.nuova_pagina()
        base = self.y - sopra
        x = self.margine
        self.canvas.setFont(self.font, self.corpo)
        for a in atomi:
            if a["tipo"] == "testo":
                self.canvas.drawString(x, base, a["testo"])
            else:
                x0 = x + self.spazio_immagine / 2
                self.canvas.drawImage(a["percorso"], x0, base - 2, width=a["img_w"], height=self.img_h,
                                      preserveAspectRatio=True, mask=None)
                self.canvas.setFont(self.font, self.corpo)
                self.canvas.drawString(x0, base - 2 - self.distanza_trattini - self.corpo * 0.75, a["trattini"])
            x += a["larghezza_con_spazio"]
        self.y = base - sotto - spazio_dopo

    def riga_vuota(self) -> None:
        self.y -= self.corpo * 0.5

    def costruisci(self) -> None:
        self.titolo(self.spec.get("titolo", ""))
        for riga in self.spec["righe"]:
            if riga == [""] or riga == [] or (len(riga) == 1 and isinstance(riga[0], str) and not riga[0].strip()):
                self.riga_vuota()
                continue
            for visiva in self.dividi_in_righe(self.atomi(riga)):
                self.riga_visiva(visiva)
        self.canvas.save()


def crea_pdf(spec_path: Path, uscita: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    Impaginatore(spec, spec_path.parent, uscita).costruisci()
    return uscita


def anteprima_png(pdf: Path, uscita: Path, larghezza_px: int = 620) -> Path:
    with pymupdf.open(pdf) as doc:
        pagina = doc[0]
        zoom = larghezza_px / pagina.rect.width
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        pix.save(str(uscita))
    return uscita


if __name__ == "__main__":  # uso: python -m app.pipeline.pdf esercizio.json uscita.pdf
    import sys

    crea_pdf(Path(sys.argv[1]), Path(sys.argv[2]))
    print("Creato:", sys.argv[2])
