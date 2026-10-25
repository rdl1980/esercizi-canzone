"""Costruisce il formato interno `esercizio.json` (lo stesso di tools/crea_esercizio.py).

righe: lista di righe; ogni riga è una lista di pezzi: stringa di testo oppure {"parola": ..., "img": ...}.
"""
import re


def _pattern(parola: str) -> re.Pattern:
    return re.compile(r"(?<![^\W\d_])" + re.escape(parola) + r"(?![^\W\d_])", re.IGNORECASE)


def costruisci_righe(blocchi: list[list[str]], selezioni: list[dict], immagini: dict[int, str]) -> list[list]:
    """`selezioni[i]` ha riga (indice piatto) e parola; `immagini[i]` è il percorso relativo dell'immagine."""
    per_riga: dict[int, list[tuple[int, dict]]] = {}
    for i, s in enumerate(selezioni):
        if i in immagini:
            per_riga.setdefault(s["riga"], []).append((i, s))
    risultato: list[list] = []
    indice = 0
    for blocco in blocchi:
        for riga in blocco:
            scelte = per_riga.get(indice, [])
            indice += 1
            if not scelte:
                risultato.append([riga])
                continue
            # posizioni delle parole nella riga (prima occorrenza di ciascuna)
            tagli: list[tuple[int, int, int, str]] = []  # (inizio, fine, i, parola_originale)
            for i, s in scelte:
                m = _pattern(s["parola"]).search(riga)
                if m and not any(a <= m.start() < b for a, b, _, _ in tagli):
                    tagli.append((m.start(), m.end(), i, m.group(0)))
            tagli.sort()
            pezzi: list = []
            pos = 0
            for inizio, fine, i, originale in tagli:
                if inizio > pos:
                    pezzi.append(riga[pos:inizio])
                pezzi.append({"parola": originale, "img": immagini[i]})
                pos = fine
            if pos < len(riga):
                pezzi.append(riga[pos:])
            risultato.append(pezzi)
        risultato.append([""])  # separatore di blocco (riga vuota)
    if risultato and risultato[-1] == [""]:
        risultato.pop()
    return risultato
