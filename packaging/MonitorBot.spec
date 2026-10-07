# PyInstaller spec for the Monitor Bot (power-user tool, console app).
# Build:  pyinstaller packaging/MonitorBot.spec
# Output: dist/MonitorBot/MonitorBot.exe
#
# Configuration is read at run time from config.py BESIDE MonitorBot.exe
# (created by `MonitorBot.exe --setup`), or from the MONITORBOT_TOKEN /
# MONITORBOT_CHAT_ID environment variables. Only the blank template
# config.example.py is bundled - never your real config.py, which holds your
# bot token and would otherwise ship inside every copy of the .exe.

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "config.example.py"), ".")]

a = Analysis(
    [os.path.join(ROOT, "monitor_bot.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["telegram.ext", "watchdog.observers", "setup_wizard"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pystray", "config"],     # config.py is loaded at run time
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
