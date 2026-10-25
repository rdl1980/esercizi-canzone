"""Costruisce l'app locale e (opzionalmente) pubblica la release su GitHub.

Uso, dalla cartella webapp/ con il venv attivo o con .venv\\Scripts\\python:
    python desktop/rilascio.py                # solo build: dist/EserciziCanzone/ e dist/EserciziCanzone-win64.zip
    python desktop/rilascio.py 1.0.1          # aggiorna app/versione.py, build, commit, tag v1.0.1, release su GitHub con lo zip
    python desktop/rilascio.py 1.0.1 --note "Corretto il download da YouTube"
"""
import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

WEBAPP = Path(__file__).resolve().parent.parent
VERSIONE_PY = WEBAPP / "app" / "versione.py"
DIST = WEBAPP / "dist"


def esegui(*args: str, cwd: Path = WEBAPP) -> None:
    print(">", " ".join(args))
    subprocess.run(args, cwd=str(cwd), check=True)


def leggi_versione() -> str:
    return re.search(r'VERSIONE\s*=\s*"([^"]+)"', VERSIONE_PY.read_text(encoding="utf-8")).group(1)


def leggi_asset() -> str:
    return re.search(r'ASSET_WINDOWS\s*=\s*"([^"]+)"', VERSIONE_PY.read_text(encoding="utf-8")).group(1)


def scrivi_versione(nuova: str) -> None:
    testo = VERSIONE_PY.read_text(encoding="utf-8")
    testo = re.sub(r'VERSIONE\s*=\s*"[^"]+"', f'VERSIONE = "{nuova}"', testo)
    VERSIONE_PY.write_text(testo, encoding="utf-8")


def build() -> Path:
    pyinstaller = WEBAPP / ".venv" / "Scripts" / "pyinstaller.exe"
    if not pyinstaller.exists():
        pyinstaller = Path(sys.executable).parent / "pyinstaller.exe"
    esegui(str(pyinstaller), "--noconfirm", "--clean", "desktop/EserciziCanzone.spec")
    cartella = DIST / "EserciziCanzone"
    if not (cartella / "EserciziCanzone.exe").exists():
        raise SystemExit("build fallita: EserciziCanzone.exe non trovato")
    zip_path = DIST / leggi_asset()
    zip_path.unlink(missing_ok=True)
    print("> zip", zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(cartella.rglob("*")):
            if f.is_file():
                z.write(f, f"EserciziCanzone/{f.relative_to(cartella).as_posix()}")
    print(f"creato {zip_path} ({zip_path.stat().st_size / 1e6:.0f} MB)")
    return zip_path


def pubblica(versione: str, note: str) -> None:
    tag = f"v{versione}"
    esegui("git", "add", "-A")
    esegui("git", "commit", "-m", f"Versione {versione}", "--allow-empty")
    esegui("git", "tag", "-a", tag, "-m", f"Versione {versione}")
    esegui("git", "push")
    esegui("git", "push", "origin", tag)
    zip_path = DIST / leggi_asset()
    esegui("gh", "release", "create", tag, str(zip_path), "--title", f"Esercizi canzone {versione}", "--notes", note or f"Versione {versione}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("versione", nargs="?", help="nuova versione (es. 1.0.1): build + release su GitHub")
    p.add_argument("--note", default="", help="note della release")
    p.add_argument("--solo-build", action="store_true", help="con la versione: aggiorna versione.py e costruisce, senza pubblicare")
    args = p.parse_args()
    if args.versione:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.versione):
            raise SystemExit("la versione deve essere del tipo 1.2.3")
        scrivi_versione(args.versione)
        print("versione impostata a", args.versione)
    build()
    if args.versione and not args.solo_build:
        pubblica(args.versione, args.note)
        print(f"pubblicata la versione {args.versione}: le app installate si aggiorneranno al prossimo avvio")


if __name__ == "__main__":
    main()
