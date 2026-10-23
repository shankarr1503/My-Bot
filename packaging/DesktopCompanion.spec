# PyInstaller spec for Desktop Companion (the store app).
# Build:  pyinstaller packaging/DesktopCompanion.spec
# Output: dist/DesktopCompanion/DesktopCompanion.exe  (windowed, no console)
#
# A folder build (not --onefile) is used on purpose: the Microsoft Store
# packages a folder, and a onefile exe unpacks to %TEMP% on every launch,
# which the Store's static analysis dislikes.

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Bundle onnxruntime (+ numpy) for the automatic background-removal feature.
# The ~168 MB U2-Net model is NOT bundled; it is downloaded once on first use
# and cached in %APPDATA%, so the installer stays small.
bg_datas, bg_binaries, bg_hidden = [], [], []
for _pkg in ("onnxruntime", "numpy"):
    _d, _b, _h = collect_all(_pkg)
    bg_datas += _d
    bg_binaries += _b
    bg_hidden += _h

a = Analysis(
    [os.path.join(ROOT, "desktop_companion.py")],
    pathex=[ROOT],
    binaries=bg_binaries,
    datas=bg_datas,
    hiddenimports=[
        "suite_common",
        "pystray._win32",       # tray backend PyInstaller may miss
        "PIL._tkinter_finder",
    ] + bg_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["cv2", "telegram", "watchdog", "psutil"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="DesktopCompanion",
    debug=False,
    strip=False,
    upx=True,
    console=False,                               # no console window
    icon=os.path.join(ROOT, "packaging", "assets", "app.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, name="DesktopCompanion",
)
