"""
Shared helpers for the Monitor Bot suite (bot, dashboard, sentinel) and the
Desktop Companion.

Standard library only, so every app - including the SYSTEM-run sentinel and
the setup wizard - can import it before any third-party package is present.

  * single-instance locks   - a named Windows mutex per app, so a second
                              launch notices the first and exits
  * where files live        - %ProgramData%\\MonitorBot once installed (only
                              Administrators can change it), else beside the
                              app, so a source checkout still just works
  * config loading          - one loader for the bot and the sentinel
  * atomic writes           - write a temp file, then swap it in, so a crash
                              mid-save never leaves a half-written file
  * admin helpers           - is_admin() / relaunch_as_admin()
"""

import ctypes
import json
import os
import sys
import tempfile

IS_WINDOWS = os.name == "nt"

# Scheduled tasks registered by install_monitor.ps1 (and the installer).
BOT_TASK = "MonitorBot-Agent"
SENTINEL_TASK = "MonitorBot-Sentinel"

# Single-instance mutex names. The bot and the dashboard live in the user's
# session ("Local\\"); the sentinel runs as SYSTEM in session 0, so it uses
# "Global\\" - SYSTEM always has the right to create global objects.
BOT_MUTEX = "Local\\MonitorBot-Agent"
DASHBOARD_MUTEX = "Local\\MonitorBot-Dashboard"
SENTINEL_MUTEX = "Global\\MonitorBot-Sentinel"
COMPANION_MUTEX = "Local\\DesktopCompanion-SingleInstance"


# ============================================================================
#  Where things live
# ============================================================================

def app_dir():
    """Folder of the running .exe (packaged) or of these scripts (source)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    """Where bundled read-only data sits (PyInstaller's _MEIPASS)."""
    return getattr(sys, "_MEIPASS", app_dir())


def installed_data_dir():
    """%ProgramData%\\MonitorBot - created and locked down by the installer."""
    base = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE")
    if not base:
        return None
    return os.path.join(base, "MonitorBot")


def data_dir():
    """Where config.py, state and logs go.

    Once installed, that's %ProgramData%\\MonitorBot, whose permissions let
    only Administrators and SYSTEM write (the bot runs elevated and imports
    config.py, so a user-writable config would be a way to run code as
    admin). A source checkout that was never installed keeps using its own
    folder, exactly as before.
    """
    d = installed_data_dir()
    if d and os.path.isdir(d):
        return d
    return app_dir()


def is_installed():
    d = installed_data_dir()
    return bool(d and os.path.isdir(d))


def config_path():
    return os.path.join(data_dir(), "config.py")


def example_config_path():
    for p in (os.path.join(data_dir(), "config.example.py"),
              os.path.join(app_dir(), "config.example.py"),
              os.path.join(bundle_dir(), "config.example.py")):
        if os.path.exists(p):
            return p
    return None


def log_path():
    return os.path.join(data_dir(), "bot.log")


# ============================================================================
#  Config
# ============================================================================

def load_config():
    """Load config.py from data_dir() (falling back to the example template),
    then let MONITORBOT_TOKEN / MONITORBOT_CHAT_ID fill any blanks.

    A plain `import config` would freeze the build machine's config.py (and
    its bot token) into a packaged build, and would also pick up a config.py
    from whatever folder the process started in.
    """
    import importlib.util
    import types
    mod = None
    for path in (config_path(), example_config_path()):
        if path and os.path.exists(path):
            spec = importlib.util.spec_from_file_location("config", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            break
    if mod is None:
        mod = types.SimpleNamespace(
            BOT_TOKEN="", CHAT_ID="",
            WATCH_FOLDER=os.path.join(os.path.expanduser("~"), "Downloads"),
            NET_CHECK_INTERVAL=60, SHUTDOWN_DELAY=30)

    token = str(getattr(mod, "BOT_TOKEN", "") or "")
    if not token or "PASTE" in token:
        mod.BOT_TOKEN = os.environ.get("MONITORBOT_TOKEN", token)
    if not str(getattr(mod, "CHAT_ID", "") or ""):
        mod.CHAT_ID = os.environ.get("MONITORBOT_CHAT_ID", "")
    mod.CHAT_ID = str(mod.CHAT_ID or "").strip()
    return mod


# ============================================================================
#  Atomic writes
# ============================================================================

def atomic_write_text(path, text, encoding="utf-8"):
    """Write `text` to `path` so readers only ever see the old or the new file,
    never a truncated one (crash, power cut, or the app killed mid-save)."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, obj, **kw):
    atomic_write_text(path, json.dumps(obj, **kw))


# ============================================================================
#  Single instance
# ============================================================================

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5
_SYNCHRONIZE = 0x00100000
_held = {}          # name -> handle / lock file, kept alive for the process


def acquire_single_instance(name):
    """Claim the app-wide lock `name`. True if we're the only copy running.

    On Windows this is a named mutex: Windows releases it automatically when
    the process exits (even if it crashes), so a stale lock can't block the
    next start. Elsewhere (development only) it's an flock'd temp file.
    """
    if name in _held:
        return True
    if IS_WINDOWS:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool,
                                     ctypes.c_wchar_p]
        h = k32.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
        if not h:
            # ACCESS_DENIED: it exists but was made by an elevated copy.
            return err != _ERROR_ACCESS_DENIED
        if err == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(ctypes.c_void_p(h))
            return False
        _held[name] = h
        return True

    import fcntl
    safe = name.replace("\\", "_").replace("/", "_")
    f = open(os.path.join(tempfile.gettempdir(), f"{safe}.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _held[name] = f
    return True


def instance_running(name):
    """True if some process currently holds the lock `name` (we don't take it)."""
    if name in _held:
        return True
    if IS_WINDOWS:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = ctypes.c_void_p
        k32.OpenMutexW.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_wchar_p]
        h = k32.OpenMutexW(_SYNCHRONIZE, False, name)
        if h:
            k32.CloseHandle(ctypes.c_void_p(h))
            return True
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED

    import fcntl
    safe = name.replace("\\", "_").replace("/", "_")
    path = os.path.join(tempfile.gettempdir(), f"{safe}.lock")
    if not os.path.exists(path):
        return False
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def bring_window_to_front(title):
    """Restore and focus the top-level window called `title`, if any."""
    if not IS_WINDOWS:
        return False
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return False
        u32.ShowWindow(hwnd, 9)          # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


# ============================================================================
#  Admin
# ============================================================================

def is_admin():
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args=()):
    """Start this program again elevated (UAC prompt). True if it launched;
    the caller should then exit."""
    if not IS_WINDOWS:
        return False
    import subprocess
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, list(sys.argv[1:])
    else:
        exe, args = sys.executable, [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    args += list(extra_args)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, subprocess.list2cmdline(args), None, 1)
    return rc > 32
