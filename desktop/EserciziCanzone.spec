# -*- mode: python ; coding: utf-8 -*-
# Build: .venv\Scripts\pyinstaller --noconfirm --clean desktop\EserciziCanzone.spec   (dalla cartella webapp/)
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

RADICE = os.path.abspath(os.path.join(SPECPATH, ".."))  # cartella webapp/, qualunque sia la cwd

datas = [(os.path.join(RADICE, "app", "templates"), "app/templates"), (os.path.join(RADICE, "app", "static"), "app/static")]
binaries = []
hiddenimports = ["app.main", "app.versione", "desktop.aggiornamenti", "desktop.strumenti"]
hiddenimports += collect_submodules("uvicorn")
for pacchetto in ("pymupdf", "anthropic"):
    d, b, h = collect_all(pacchetto)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(RADICE, "desktop", "avvio.py")],
    pathex=[RADICE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "IPython", "matplotlib", "numpy", "pandas", "docx"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EserciziCanzone",
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EserciziCanzone")
