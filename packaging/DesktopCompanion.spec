# PyInstaller spec for Desktop Companion (the store app).
# Build:  pyinstaller packaging/DesktopCompanion.spec
# Output: dist/DesktopCompanion/DesktopCompanion.exe  (windowed, no console)
#
# A folder build (not --onefile) is used on purpose: the Microsoft Store
# packages a folder, and a onefile exe unpacks to %TEMP% on every launch,
# which the Store's static analysis dislikes.

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "desktop_companion.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        "pystray._win32",       # tray backend PyInstaller may miss
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["cv2", "numpy", "telegram", "watchdog", "psutil"],
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
