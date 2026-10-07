# PyInstaller spec for the Monitor Bot (power-user tool, console app).
# Build:  pyinstaller packaging/MonitorBot.spec
# Output: dist/MonitorBot/MonitorBot.exe
#
# The bot reads config.py next to the exe (or MONITORBOT_TOKEN /
# MONITORBOT_CHAT_ID environment variables), so config.py is bundled as data
# and can also be edited beside the packaged exe.

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

cfg = os.path.join(ROOT, "config.py")
datas = []
if os.path.exists(cfg):
    datas.append((cfg, "."))

a = Analysis(
    [os.path.join(ROOT, "monitor_bot.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["telegram.ext", "watchdog.observers", "setup_wizard"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pystray"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MonitorBot",
    debug=False,
    strip=False,
    upx=True,
    console=True,
    icon=os.path.join(ROOT, "packaging", "assets", "app.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, name="MonitorBot",
)
