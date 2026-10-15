# PyInstaller spec for the Monitor Bot Dashboard (the GUI + the bot in one app).
# Build:  pyinstaller packaging/MonitorBotDashboard.spec
# Output: dist/MonitorBotDashboard/MonitorBotDashboard.exe  (windowed)
#
# One executable: it opens the dashboard by default and runs the bot when
# started with --bot (how the dashboard's Start button launches it). It is
# windowed (no console), so --setup opens the dashboard - whose Connect tab is
# the GUI setup - instead of the console wizard. config.py is read at run time
# from beside the exe; only the blank config.example.py template is bundled.

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "monitor_app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "config.example.py"), ".")],
    hiddenimports=[
        "bot_dashboard", "monitor_bot", "setup_wizard",
        "telegram.ext", "watchdog.observers", "psutil",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pystray", "config"],   # config.py is loaded at run time
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MonitorBotDashboard",
    debug=False,
    strip=False,
    upx=True,
    console=False,                               # windowed: shows the dashboard
    icon=os.path.join(ROOT, "packaging", "assets", "app.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, name="MonitorBotDashboard",
)
