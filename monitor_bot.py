"""
Laptop Monitor Bot  -  reports your Windows laptop to Telegram.

Commands you send the bot:
  /status      -> CPU, RAM, disk, battery summary
  /screenshot  -> current screen as a photo
  /disk        -> usage of every drive
  /net         -> current internet status
  /myid        -> shows your chat id (needed once, during setup)
  /help        -> this list

Automatic alerts (need CHAT_ID set in config.py):
  - "Laptop online" when the bot starts
  - Internet lost / restored
  - New file appears in the watched folder (default: Downloads)

Only your own chat id can use the sensitive commands, so nobody who
stumbles onto the bot can screenshot your screen.
"""

import asyncio
import ctypes
import functools
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

# `--setup` runs the stdlib-only wizard before anything a fresh install may be
# missing: the third-party packages below, or config.py itself (the wizard is
# what creates it).
if __name__ == "__main__" and "--setup" in sys.argv:
    import setup_wizard
    setup_wizard.main()
    sys.exit(0)

import psutil
from PIL import ImageGrab
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def _load_config():
    """Load config.py from beside this script - or beside the .exe in a
    PyInstaller build - so the user's edits apply without rebuilding.

    A plain `import config` would freeze the build machine's config.py (and
    its bot token) into the executable. With no config.py yet, fall back to
    the defaults in config.example.py; credentials can then still come from
    the MONITORBOT_* environment variables.
    """
    import importlib.util
    import types
    if getattr(sys, "frozen", False):
        here = os.path.dirname(sys.executable)
        bundle = getattr(sys, "_MEIPASS", here)
    else:
        here = bundle = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "config.py"),
                 os.path.join(here, "config.example.py"),
                 os.path.join(bundle, "config.example.py")):
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("config", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return types.SimpleNamespace(
        BOT_TOKEN="", CHAT_ID="",
        WATCH_FOLDER=os.path.join(os.path.expanduser("~"), "Downloads"),
        NET_CHECK_INTERVAL=60, SHUTDOWN_DELAY=30)


config = _load_config()

# Let environment variables fill in anything config.py left blank. This lets a
# packaged build inject credentials without the user editing a .py file.
if not getattr(config, "BOT_TOKEN", "") or "PASTE" in config.BOT_TOKEN:
    config.BOT_TOKEN = os.environ.get("MONITORBOT_TOKEN", config.BOT_TOKEN)
if not getattr(config, "CHAT_ID", ""):
    config.CHAT_ID = os.environ.get("MONITORBOT_CHAT_ID", config.CHAT_ID)


# ----------------------------- helpers -----------------------------

def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def internet_up(host="8.8.8.8", port=53, timeout=3):
    """True if we can open a socket to a public DNS server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)          # per-socket, not a global default
            s.connect((host, port))
        return True
    except OSError:
        return False


def build_status(bold=True):
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    title = "*Laptop status*" if bold else "Laptop status"
    lines = [
        f"{title}  ({datetime.now():%Y-%m-%d %H:%M:%S})",
        f"CPU:  {cpu:.0f}%",
        f"RAM:  {mem.percent:.0f}%   ({human_bytes(mem.used)} / {human_bytes(mem.total)})",
        f"Disk C:  {disk.percent:.0f}%   ({human_bytes(disk.free)} free)",
    ]
    batt = psutil.sensors_battery()
    if batt is not None:
        plug = "charging" if batt.power_plugged else "on battery"
        lines.append(f"Battery:  {batt.percent:.0f}%  ({plug})")
    return "\n".join(lines)


PS_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _powershell(script, timeout=20):
    """Run a PowerShell snippet, return stdout (or "" if anything goes wrong)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, **PS_FLAGS,
        )
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def wifi_info():
    """Which network we're on.

    Uses Get-NetConnectionProfile because, unlike `netsh wlan show
    interfaces`, it needs neither admin rights nor Location services -- both
    of which Windows 11 demands before it will reveal an SSID.
    Returns a dict, or None if nothing is connected.
    """
    out = _powershell(
        "$p = Get-NetConnectionProfile | "
        "Where-Object { $_.IPv4Connectivity -eq 'Internet' } | Select-Object -First 1; "
        "if ($p) { $a = Get-NetAdapter -InterfaceAlias $p.InterfaceAlias "
        "-ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ name=$p.Name; alias=$p.InterfaceAlias; "
        "category=[string]$p.NetworkCategory; speed=[string]$a.LinkSpeed } "
        "| ConvertTo-Json -Compress }"
    )
    if not out:
        return None
    try:
        info = json.loads(out)
    except ValueError:
        return None

    # Signal strength only comes back when Location services is switched on.
    # Without it we just go without, rather than failing the whole report.
    sig = _powershell("(netsh wlan show interfaces | Select-String 'Signal' | Select-Object -First 1).ToString()", timeout=15)
    if sig and ":" in sig:
        info["signal"] = sig.split(":", 1)[1].strip()
    return info


def ip_location():
    """Rough location from the public IP. None if it can't be determined.

    This is the ISP's exit point, not the laptop -- on a mobile carrier it can
    land hundreds of km away. Useful for "which city, has the network changed",
    not for finding a lost machine.
    """
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=12) as r:
            d = json.load(r)
        return {
            "ip": d.get("ip"), "city": d.get("city"), "region": d.get("region"),
            "country": d.get("country"), "loc": d.get("loc"), "org": d.get("org"),
        }
    except Exception:
        pass
    try:  # fallback, a different provider
        url = ("http://ip-api.com/json/?fields=status,country,regionName,city,"
               "lat,lon,isp,query")
        with urllib.request.urlopen(url, timeout=12) as r:
            d = json.load(r)
        if d.get("status") != "success":
            return None
        loc = f"{d.get('lat')},{d.get('lon')}" if d.get("lat") is not None else None
        return {
            "ip": d.get("query"), "city": d.get("city"), "region": d.get("regionName"),
            "country": d.get("country"), "loc": loc, "org": d.get("isp"),
        }
    except Exception:
        return None


def build_where():
    """Plain-text Wi-Fi + location block."""
    lines = []
    w = wifi_info()
    if w:
        lines.append(f"Network:  {w.get('name') or 'unknown'}")
        bits = [b for b in (w.get("alias"), w.get("speed"),
                            w.get("category") and f"{w['category']} network") if b]
        if bits:
            lines.append("  " + "  -  ".join(bits))
        if w.get("signal"):
            lines.append(f"  signal {w['signal']}")
    else:
        lines.append("Network:  not connected")

    if getattr(config, "LOCATION_ENABLED", True):
        g = ip_location()
        if g:
            place = ", ".join(x for x in (g.get("city"), g.get("region"),
                                          g.get("country")) if x)
            lines.append("")
            lines.append("Approx. location (from public IP - city level, often off):")
            if place:
                lines.append(f"  {place}")
            tail = [x for x in (g.get("ip"), g.get("org")) if x]
            if tail:
                lines.append("  " + "  -  ".join(tail))
            if g.get("loc"):
                lines.append(f"  https://www.google.com/maps?q={g['loc']}")
        else:
            lines.append("")
            lines.append("Location:  unavailable (lookup failed)")
    return "\n".join(lines)


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "app_state.json")
TG_LIMIT = 4096          # Telegram rejects anything longer


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(d):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass


def app_inventory():
    """Split everything running into on-screen apps, background, and system.

    "On screen" means the process owns a visible top-level window, which is
    what PowerShell's MainWindowTitle reports. Everything else running under
    your own account counts as background; anything under SYSTEM and friends
    is Windows itself and only gets counted, not listed.
    """
    windowed = {}
    out = _powershell(
        "Get-Process | Where-Object { $_.MainWindowTitle -ne '' } | "
        "Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json -Compress")
    if out:
        try:
            data = json.loads(out)
            if isinstance(data, dict):        # one result is not a list
                data = [data]
            for it in data:
                windowed[int(it["Id"])] = str(it.get("MainWindowTitle") or "")
        except (ValueError, KeyError, TypeError):
            pass

    try:
        me = psutil.Process().username()
    except Exception:
        me = None

    open_apps, background, system = [], {}, 0
    for pr in psutil.process_iter(["pid", "name", "username", "memory_info"]):
        i = pr.info
        name = i.get("name") or "?"
        mi = i.get("memory_info")
        mem = mi.rss if mi else 0
        if i.get("pid") in windowed:
            open_apps.append((name, windowed[i["pid"]], mem))
        elif me and i.get("username") == me:
            background[name] = background.get(name, 0) + mem
        else:
            system += 1
    return {"open": open_apps, "background": background, "system": system}


def build_app_report():
    """The 5-hourly app report, including what changed since the last one."""
    inv = app_inventory()
    open_names = {n for n, _, _ in inv["open"]}
    now_names = sorted(open_names | set(inv["background"]))

    state = _load_state()
    prev, prev_time = state.get("apps"), state.get("time")

    L = [f"App report  ({datetime.now():%Y-%m-%d %H:%M})"]
    if prev_time:
        L.append(f"changes measured against {prev_time}")
    L.append("")

    L.append(f"OPEN - has a window on screen  ({len(inv['open'])})")
    if inv["open"]:
        for name, title, mem in sorted(inv["open"], key=lambda x: -x[2])[:12]:
            title = (title[:40] + "...") if len(title) > 43 else title
            L.append(f"  {name}  ({human_bytes(mem)})")
            if title:
                L.append(f"      {title}")
        if len(inv["open"]) > 12:
            L.append(f"  ... and {len(inv['open']) - 12} more")
    else:
        L.append("  (none)")

    bg = sorted(inv["background"].items(), key=lambda kv: -kv[1])
    L.append("")
    L.append(f"BACKGROUND - running, no window  ({len(bg)})")
    for name, mem in bg[:15]:
        L.append(f"  {name}  ({human_bytes(mem)})")
    if len(bg) > 15:
        L.append(f"  ... and {len(bg) - 15} more")

    L.append("")
    L.append(f"Windows system processes:  {inv['system']}")

    L.append("")
    if prev is None:
        L.append("This is the first report, so there is nothing to compare")
        L.append("against yet. The next one will list what opened and closed.")
    else:
        opened = sorted(set(now_names) - set(prev))
        closed = sorted(set(prev) - set(now_names))
        L.append(f"OPENED since last report  ({len(opened)})")
        L.append("  " + (", ".join(opened[:25]) if opened else "nothing new"))
        L.append("")
        L.append(f"CLOSED since last report  ({len(closed)})")
        L.append("  " + (", ".join(closed[:25]) if closed else "nothing closed"))

    _save_state({"apps": now_names, "time": f"{datetime.now():%Y-%m-%d %H:%M}"})

    text = "\n".join(L)
    if len(text) > TG_LIMIT:
        text = text[:TG_LIMIT - 20].rsplit("\n", 1)[0] + "\n... (truncated)"
    return text


def build_report():
    """The full push: status + network + location, as plain text.

    Deliberately not Markdown -- network and ISP names arrive with characters
    like _ and * in them, and one stray character makes Telegram reject the
    entire message.
    """
    return build_status(bold=False) + "\n\n" + build_where()


def grab_screenshot():
    img = ImageGrab.grab()
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path


def grab_webcam(index=None, warmup=None):
    """Take one still from the webcam. Returns a file path, or None.

    OpenCV is imported lazily so the bot still runs (minus this feature) if
    opencv-python is not installed. The first few frames are discarded on
    purpose -- a webcam's first frame is usually black or badly exposed
    because gain and exposure have not settled yet.
    """
    try:
        import cv2
    except ImportError:
        return None
    if index is None:
        index = getattr(config, "CAMERA_INDEX", 0)
    if warmup is None:
        warmup = getattr(config, "CAMERA_WARMUP", 8)

    cap = None
    try:
        # CAP_DSHOW is markedly faster to open than the default backend on
        # Windows; fall back to the default if DirectShow is unavailable.
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            return None
        frame = None
        for _ in range(max(1, warmup)):
            ok, f = cap.read()
            if ok:
                frame = f
            time.sleep(0.06)
        if frame is None:
            return None
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path
    except Exception:
        return None
    finally:
        if cap is not None:
            cap.release()


def owner_only(func):
    """Ignore commands from anyone who isn't the configured owner.

    Until CHAT_ID is set nobody passes -- an unconfigured bot must not hand
    out screenshots to whoever finds it first. /myid stays open so you can
    still finish setup.
    """
    @functools.wraps(func)
    async def wrapper(update, context):
        if not config.CHAT_ID:
            await update.message.reply_text(
                "Not set up yet. Send /myid and paste the number into "
                "config.py as CHAT_ID, then restart the bot."
            )
            return
        if str(update.effective_chat.id) != str(config.CHAT_ID):
            return
        return await func(update, context)
    return wrapper


# ---------------------------- commands -----------------------------

HELP = (
    "Laptop Monitor Bot\n\n"
    "INFO\n"
    "/status - CPU, RAM, disk, battery\n"
    "/battery - detailed battery / power\n"
    "/uptime - how long it's been on\n"
    "/disk - usage of every drive\n"
    "/net - internet status\n"
    "/where - Wi-Fi network + approximate location\n"
    "/apps - what is running, open and closed\n"
    "/top - busiest processes right now\n"
    "/recent - newest files in the watched folder\n"
    "/weather [city] - current weather\n"
    "/ping - quick are-you-alive check\n\n"
    "CAPTURE\n"
    "/screenshot - photo of the current screen\n"
    "/photo - webcam photo\n"
    "/clipboard - read the laptop's clipboard\n\n"
    "CONTROL\n"
    "/lock - lock the screen\n"
    "/sleep - put the laptop to sleep\n"
    "/notify <msg> - pop a message on the laptop screen\n"
    "/speak <msg> - say something out loud on the laptop\n"
    "/mute - toggle mute\n"
    "/volup [n] /voldown [n] - nudge the volume\n"
    "/kill <app> - close an app by name\n"
    "/shutdown - shut down (asks you to confirm)\n"
    "/abort - call off a shutdown\n\n"
    "SECURITY (Microsoft Defender)\n"
    "/security - protection status + firewall + BitLocker\n"
    "/scan [quick|full|<path>] - run an antivirus scan\n"
    "/threats - threats Defender has found\n"
    "/clean - remove active threats\n"
    "/defupdate - update virus definitions\n"
    "/protect - turn real-time protection back on\n"
    "/firewall [status|on|off] - Windows Firewall\n\n"
    "SETUP\n"
    "/myid - show your chat id\n"
    "/help - this message"
)


@owner_only
async def cmd_help(update, context):
    await update.message.reply_text(HELP)


@owner_only
async def cmd_status(update, context):
    text = await asyncio.to_thread(build_report)
    await update.message.reply_text(text, disable_web_page_preview=True)


@owner_only
async def cmd_screenshot(update, context):
    await context.bot.send_chat_action(update.effective_chat.id, "upload_photo")
    path = await asyncio.to_thread(grab_screenshot)
    try:
        with open(path, "rb") as f:
            await update.message.reply_photo(f, caption="Current screen")
    finally:
        os.remove(path)


@owner_only
async def cmd_photo(update, context):
    await context.bot.send_chat_action(update.effective_chat.id, "upload_photo")
    path = await asyncio.to_thread(grab_webcam)
    if not path:
        await update.message.reply_text(
            "Couldn't take a photo - camera busy, disabled, or "
            "opencv-python not installed.")
        return
    try:
        with open(path, "rb") as f:
            await update.message.reply_photo(f, caption="Webcam")
    finally:
        os.remove(path)


@owner_only
async def cmd_disk(update, context):
    rows = []
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        rows.append(f"{p.device}  {u.percent:.0f}%  ({human_bytes(u.free)} free)")
    await update.message.reply_text("\n".join(rows) or "No drives found.")


@owner_only
async def cmd_net(update, context):
    up = await asyncio.to_thread(internet_up)
    await update.message.reply_text("Internet: ONLINE" if up else "Internet: OFFLINE")


@owner_only
async def cmd_where(update, context):
    text = await asyncio.to_thread(build_where)
    await update.message.reply_text(text, disable_web_page_preview=True)


async def cmd_myid(update, context):
    # deliberately NOT owner-only, so you can discover your id during setup
    await update.message.reply_text(
        f"Your chat id is: {update.effective_chat.id}\n"
        "Paste it into config.py as CHAT_ID, then restart the bot."
    )


# ------------------------ background alerts ------------------------

async def check_internet(context: ContextTypes.DEFAULT_TYPE):
    up = await asyncio.to_thread(internet_up)
    prev = context.bot_data.get("net_up")
    context.bot_data["net_up"] = up
    if prev is not None and up != prev:
        msg = "Internet restored." if up else "Internet lost."
        await context.bot.send_message(config.CHAT_ID, msg)


async def hourly_report(context: ContextTypes.DEFAULT_TYPE):
    text = await asyncio.to_thread(build_report)
    await context.bot.send_message(config.CHAT_ID, text,
                                   disable_web_page_preview=True)


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, loop, bot):
        self.loop = loop
        self.bot = bot

    def on_created(self, event):
        if event.is_directory:
            return
        name = os.path.basename(event.src_path)
        # skip browsers' half-finished download files
        if name.endswith((".crdownload", ".tmp", ".part", ".partial")):
            return
        asyncio.run_coroutine_threadsafe(
            self.bot.send_message(config.CHAT_ID, f"New file: {name}"),
            self.loop,
        )


def _send_now(text, timeout=4):
    """Fire off one Telegram message synchronously, from any thread.

    Used by the shutdown guard, which runs outside the event loop and has
    only a couple of seconds before Windows kills the process.
    """
    try:
        data = urllib.parse.urlencode(
            {"chat_id": config.CHAT_ID, "text": text}).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            data, timeout=timeout)
    except Exception:
        pass


def do_shutdown(delay):
    return subprocess.run(
        ["shutdown", "/s", "/t", str(delay), "/c",
         "Shutdown approved from Telegram."],
        capture_output=True, text=True, **PS_FLAGS)


def do_abort():
    return subprocess.run(["shutdown", "/a"], capture_output=True, text=True,
                          **PS_FLAGS)


@owner_only
async def cmd_shutdown(update, context):
    inv = await asyncio.to_thread(app_inventory)
    batt = psutil.sensors_battery()
    bits = [f"{len(inv['open'])} apps open on screen"]
    if batt is not None:
        bits.append(f"battery {batt.percent:.0f}%")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm shutdown", callback_data="sd:yes"),
        InlineKeyboardButton("Cancel", callback_data="sd:no"),
    ]])
    await update.message.reply_text(
        "Shut down this laptop?\n" + "  -  ".join(bits) +
        f"\n\nUnsaved work in those apps may be lost."
        f"\nYou get {config.SHUTDOWN_DELAY}s to send /abort afterwards.",
        reply_markup=kb)


async def on_button(update, context):
    """Handle the Confirm / Cancel buttons."""
    q = update.callback_query
    # Buttons carry their own authorisation check -- owner_only guards
    # messages, not callbacks.
    if not config.CHAT_ID or str(q.message.chat.id) != str(config.CHAT_ID):
        await q.answer("Not allowed.", show_alert=True)
        return
    await q.answer()
    if q.data == "sd:no":
        await q.edit_message_text("Cancelled. Nothing was shut down.")
        return
    if q.data == "sd:yes":
        r = await asyncio.to_thread(do_shutdown, config.SHUTDOWN_DELAY)
        if r.returncode == 0:
            await q.edit_message_text(
                f"Approved. Shutting down in {config.SHUTDOWN_DELAY}s.\n"
                "Send /abort now if you change your mind.")
        else:
            await q.edit_message_text(
                "Shutdown command failed:\n"
                + ((r.stderr or r.stdout).strip()[:300] or f"exit {r.returncode}"))


@owner_only
async def cmd_abort(update, context):
    r = await asyncio.to_thread(do_abort)
    if r.returncode == 0:
        await update.message.reply_text("Shutdown aborted.")
    else:
        await update.message.reply_text(
            "Nothing to abort - no shutdown was in progress.")


@owner_only
async def cmd_apps(update, context):
    text = await asyncio.to_thread(build_app_report)
    await update.message.reply_text(text)


async def app_report_job(context: ContextTypes.DEFAULT_TYPE):
    text = await asyncio.to_thread(build_app_report)
    await context.bot.send_message(config.CHAT_ID, text)


# ======================================================================
#  Extra remote-control / convenience features
# ======================================================================

# Processes we refuse to kill - taking these down can bluescreen or lock
# you out of the machine. The /kill command is owner-only on top of this.
PROTECTED = {
    "system", "system idle process", "wininit.exe", "winlogon.exe",
    "csrss.exe", "services.exe", "lsass.exe", "smss.exe", "explorer.exe",
    "svchost.exe", "dwm.exe", "fontdrvhost.exe", "python.exe", "pythonw.exe",
}

# Media-key virtual codes, used for volume without any extra dependency.
_VK = {"mute": 0xAD, "down": 0xAE, "up": 0xAF}


def _press_media_key(which, times=1):
    if os.name != "nt":
        return False
    try:
        vk = _VK[which]
        for _ in range(max(1, times)):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
        return True
    except Exception:
        return False


def lock_workstation():
    try:
        return bool(ctypes.windll.user32.LockWorkStation())
    except Exception:
        return False


def sleep_machine():
    # SetSuspendState(hibernate=False, force=False, wakeup=False)
    try:
        ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
        return True
    except Exception:
        return False


def message_box(text, title="Message from you"):
    """Show a desktop pop-up on the laptop. Blocks until someone clicks OK,
    so only ever call it from show_notification's background thread."""
    try:
        MB_OK, MB_TOPMOST, MB_ICONINFO = 0x0, 0x40000, 0x40
        ctypes.windll.user32.MessageBoxW(
            0, str(text), str(title), MB_OK | MB_TOPMOST | MB_ICONINFO)
        return True
    except Exception:
        return False


_NOTIFY_SLOTS = threading.BoundedSemaphore(3)   # max pop-ups on screen at once


def show_notification(text):
    """Pop a message box without waiting for anyone to dismiss it.

    The box is modal, and the bot handles one command at a time, so awaiting
    it would freeze every command - /abort included - until someone at the
    laptop clicked OK. Returns False if 3 pop-ups are already open.
    """
    if not _NOTIFY_SLOTS.acquire(blocking=False):
        return False

    def run():
        try:
            message_box(text)
        finally:
            _NOTIFY_SLOTS.release()

    threading.Thread(target=run, daemon=True).start()
    return True


def speak(text):
    """Text-to-speech through Windows' built-in voice."""
    safe = str(text).replace("'", "''")
    out = _powershell(
        "Add-Type -AssemblyName System.Speech; "
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
        f".Speak('{safe}')", timeout=30)
    return out is not None


def get_clipboard():
    return _powershell("Get-Clipboard -Raw", timeout=10)


def fetch_weather(city=""):
    """One-line weather from wttr.in (no API key)."""
    q = urllib.parse.quote(city.strip())
    url = f"https://wttr.in/{q}?format=%l:+%c+%t+(feels+%f),+%h+humidity,+wind+%w"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception:
        return None


def battery_detail():
    b = psutil.sensors_battery()
    if b is None:
        return "No battery detected (desktop, or driver hidden)."
    lines = [f"Battery:  {b.percent:.0f}%",
             "Power:  " + ("charging / plugged in" if b.power_plugged
                           else "on battery")]
    if b.secsleft not in (psutil.POWER_TIME_UNLIMITED,
                          psutil.POWER_TIME_UNKNOWN) and b.secsleft > 0:
        h, m = divmod(b.secsleft // 60, 60)
        lines.append(f"Time left:  ~{h}h {m}m")
    return "\n".join(lines)


def uptime_text():
    boot = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot
    d = delta.days
    h, rem = divmod(delta.seconds, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    parts += [f"{h}h", f"{m}m"]
    return (f"Booted:  {boot:%Y-%m-%d %H:%M}\n"
            f"Uptime:  {' '.join(parts)}")


def top_processes(n=6):
    psutil.cpu_percent(interval=None)        # prime the per-process counters
    procs = list(psutil.process_iter(["name", "memory_info"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.6)
    rows = []
    for p in procs:
        try:
            cpu = p.cpu_percent(None)
            mi = p.info.get("memory_info")
            rows.append((p.info.get("name") or "?", cpu,
                         mi.rss if mi else 0))
        except Exception:
            continue
    cores = psutil.cpu_count() or 1
    by_cpu = sorted(rows, key=lambda r: -r[1])[:n]
    by_mem = sorted(rows, key=lambda r: -r[2])[:n]
    L = ["Top by CPU:"]
    for name, cpu, _ in by_cpu:
        L.append(f"  {name}  {cpu / cores:.0f}%")
    L.append("")
    L.append("Top by memory:")
    for name, _, mem in by_mem:
        L.append(f"  {name}  {human_bytes(mem)}")
    return "\n".join(L)


def kill_by_name(name):
    """Terminate every process whose name matches (case-insensitive)."""
    name = name.strip().lower()
    if not name.endswith(".exe"):
        name += ".exe"
    if name in PROTECTED:
        return -1
    killed = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() == name:
                p.terminate()
                killed += 1
        except Exception:
            continue
    return killed


@owner_only
async def cmd_lock(update, context):
    ok = await asyncio.to_thread(lock_workstation)
    await update.message.reply_text("Laptop locked." if ok
                                    else "Couldn't lock the workstation.")


@owner_only
async def cmd_sleep(update, context):
    await update.message.reply_text("Putting the laptop to sleep...")
    await asyncio.to_thread(sleep_machine)


@owner_only
async def cmd_uptime(update, context):
    await update.message.reply_text(await asyncio.to_thread(uptime_text))


@owner_only
async def cmd_battery(update, context):
    await update.message.reply_text(await asyncio.to_thread(battery_detail))


@owner_only
async def cmd_top(update, context):
    await update.message.reply_text(await asyncio.to_thread(top_processes))


@owner_only
async def cmd_clipboard(update, context):
    text = await asyncio.to_thread(get_clipboard)
    if not text:
        await update.message.reply_text("Clipboard is empty or unavailable.")
        return
    prefix, marker = "Clipboard:\n", "\n...(truncated)"
    room = TG_LIMIT - len(prefix)
    if len(text) > room:
        text = text[:room - len(marker)] + marker
    await update.message.reply_text(prefix + text)


@owner_only
async def cmd_notify(update, context):
    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("Usage: /notify your message here")
        return
    if show_notification(msg):
        await update.message.reply_text("Shown on the laptop screen.")
    else:
        await update.message.reply_text(
            "3 messages are already waiting on the laptop screen - "
            "try again once someone has closed them.")


@owner_only
async def cmd_speak(update, context):
    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("Usage: /speak something to say out loud")
        return
    await asyncio.to_thread(speak, msg)
    await update.message.reply_text("Said it out loud.")


@owner_only
async def cmd_weather(update, context):
    city = " ".join(context.args) if context.args else ""
    text = await asyncio.to_thread(fetch_weather, city)
    await update.message.reply_text(text or "Couldn't fetch weather.",
                                    disable_web_page_preview=True)


@owner_only
async def cmd_mute(update, context):
    ok = await asyncio.to_thread(_press_media_key, "mute", 1)
    await update.message.reply_text("Toggled mute." if ok
                                    else "Couldn't change volume.")


@owner_only
async def cmd_volup(update, context):
    steps = 3
    if context.args and context.args[0].isdigit():
        steps = max(1, min(20, int(context.args[0])))
    ok = await asyncio.to_thread(_press_media_key, "up", steps)
    await update.message.reply_text(f"Volume up ({steps} steps)." if ok
                                    else "Couldn't change volume.")


@owner_only
async def cmd_voldown(update, context):
    steps = 3
    if context.args and context.args[0].isdigit():
        steps = max(1, min(20, int(context.args[0])))
    ok = await asyncio.to_thread(_press_media_key, "down", steps)
    await update.message.reply_text(f"Volume down ({steps} steps)." if ok
                                    else "Couldn't change volume.")


@owner_only
async def cmd_kill(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /kill chrome   (name of the app)")
        return
    name = context.args[0]
    n = await asyncio.to_thread(kill_by_name, name)
    if n == -1:
        await update.message.reply_text(
            f"Refused: {name} is a protected system process.")
    elif n == 0:
        await update.message.reply_text(f"No running process named '{name}'.")
    else:
        await update.message.reply_text(f"Terminated {n} '{name}' process(es).")


@owner_only
async def cmd_recent(update, context):
    folder = config.WATCH_FOLDER
    try:
        items = [(f, os.path.getmtime(os.path.join(folder, f)))
                 for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f))]
    except OSError:
        await update.message.reply_text("Can't read the watched folder.")
        return
    items.sort(key=lambda x: -x[1])
    if not items:
        await update.message.reply_text("No files in the watched folder.")
        return
    lines = [f"Recent files in {os.path.basename(folder) or folder}:"]
    for f, mt in items[:10]:
        lines.append(f"  {f}   ({datetime.fromtimestamp(mt):%m-%d %H:%M})")
    await update.message.reply_text("\n".join(lines))


async def cmd_ping(update, context):
    await update.message.reply_text("I'm awake. Laptop is on and the bot is running.")


# ======================================================================
#  Security / Antivirus  -  driven by Microsoft Defender
# ======================================================================
#
# Rather than pretend to be an antivirus, the bot acts as a remote control
# for Microsoft Defender - the AV engine built into Windows, which rates at
# the top of independent AV-TEST results. The bot can report protection
# status, run real scans, update virus definitions, list detected threats,
# remove them, and alert you when Defender finds something or when real-time
# protection gets switched off.
#
# Note: a few of these (full/custom scan, Update-MpSignature, Remove-MpThreat,
# turning real-time protection on, reading BitLocker) may need the bot to run
# as administrator. Status and quick scans work without elevation.

def _ps_run(script, timeout=60):
    """Run PowerShell and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, **PS_FLAGS)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -2, "", "timed out"
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def defender_status_raw():
    out = _powershell(
        "$s=Get-MpComputerStatus; [pscustomobject]@{"
        "svc=$s.AMServiceEnabled; rtp=$s.RealTimeProtectionEnabled;"
        "av=$s.AntivirusEnabled; asp=$s.AntispywareEnabled; nis=$s.NISEnabled;"
        "sig=[string]$s.AntivirusSignatureVersion; age=$s.AntivirusSignatureAge;"
        "quick=[string]$s.QuickScanEndTime; full=[string]$s.FullScanEndTime;"
        "tamper=$s.IsTamperProtected} | ConvertTo-Json -Compress", timeout=30)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def build_defender_status():
    d = defender_status_raw()
    if not d:
        return ("Microsoft Defender status unavailable.\n"
                "(Needs Windows with Defender; another AV may have replaced it.)")
    yn = lambda b: "ON" if b else "OFF"            # noqa: E731
    return "\n".join([
        "Microsoft Defender Antivirus",
        f"  Service running:        {yn(d.get('svc'))}",
        f"  Real-time protection:   {yn(d.get('rtp'))}",
        f"  Antivirus / antispyware:{yn(d.get('av'))} / {yn(d.get('asp'))}",
        f"  Network protection:     {yn(d.get('nis'))}",
        f"  Tamper protection:      {yn(d.get('tamper'))}",
        f"  Definitions:            v{d.get('sig','?')}  "
        f"({d.get('age','?')} day(s) old)",
        f"  Last quick scan:        {d.get('quick') or 'never'}",
        f"  Last full scan:         {d.get('full') or 'never'}",
    ])


_SEVERITY = {0: "", 1: "Low", 2: "Moderate", 4: "High", 5: "Severe"}
_THREAT_STATUS = {
    0: "Unknown", 1: "Detected", 2: "Cleaned", 3: "Quarantined",
    4: "Removed", 5: "Allowed", 6: "Blocked", 102: "No action taken",
    106: "Cleaned (reboot needed)",
}


def build_threats():
    out = _powershell(
        "Get-MpThreat | Sort-Object InitialDetectionTime -Descending | "
        "Select-Object -First 15 ThreatName, SeverityID, ThreatStatusID, "
        "@{n='t';e={[string]$_.InitialDetectionTime}} | ConvertTo-Json -Compress",
        timeout=45)
    if not out:
        return "No threats on record. Microsoft Defender hasn't flagged anything."
    try:
        data = json.loads(out)
    except ValueError:
        return "No threats on record."
    if isinstance(data, dict):
        data = [data]
    if not data:
        return "No threats on record. You're clean."
    L = [f"Defender threat history ({len(data)} shown)"]
    for it in data:
        name = it.get("ThreatName", "?")
        sev = _SEVERITY.get(it.get("SeverityID"), "")
        st = _THREAT_STATUS.get(it.get("ThreatStatusID"), str(it.get("ThreatStatusID")))
        when = it.get("t", "")
        L.append(f"  • {name}")
        tag = f"{sev} | " if sev else ""
        L.append(f"      {tag}{st}   {when}")
    text = "\n".join(L)
    return text[:TG_LIMIT - 20] if len(text) > TG_LIMIT else text


def run_scan(scan_type="QuickScan", path=None, timeout=1800):
    if path:
        safe = path.replace("'", "''")
        script = f"Start-MpScan -ScanType CustomScan -ScanPath '{safe}'"
    else:
        script = f"Start-MpScan -ScanType {scan_type}"
    rc, _, _ = _ps_run(script, timeout=timeout)
    return rc


def start_full_scan_detached():
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Start-MpScan -ScanType FullScan"], **PS_FLAGS)
        return True
    except Exception:
        return False


def update_signatures():
    rc, out, err = _ps_run("Update-MpSignature; 'OK'", timeout=180)
    return rc, (err or out)


def enable_realtime():
    rc, _, err = _ps_run(
        "Set-MpPreference -DisableRealtimeMonitoring $false", timeout=30)
    return rc == 0, err


def remove_threats():
    rc, out, err = _ps_run("Remove-MpThreat; 'done'", timeout=600)
    return rc, (err or out)


def firewall_status():
    out = _powershell(
        "Get-NetFirewallProfile | Select-Object Name,Enabled | "
        "ConvertTo-Json -Compress", timeout=20)
    try:
        data = json.loads(out) if out else []
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    return {d.get("Name"): bool(d.get("Enabled")) for d in data}


def firewall_set(enabled):
    """Enable/disable all Windows Firewall profiles. Needs admin."""
    val = "True" if enabled else "False"
    rc, _, err = _ps_run(
        f"Set-NetFirewallProfile -All -Enabled {val}", timeout=30)
    return rc == 0, err


def pending_updates():
    """Count pending Windows updates via the Update COM API. Best-effort;
    returns an int, or None if it can't be determined (offline/slow/blocked)."""
    out = _powershell(
        "try{$s=New-Object -ComObject Microsoft.Update.Session;"
        "$r=$s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Software'\");"
        "$r.Updates.Count}catch{''}", timeout=60)
    try:
        return int(out) if out not in ("", None) else None
    except (TypeError, ValueError):
        return None


def bitlocker_status():
    out = _powershell(
        "try{[string](Get-BitLockerVolume -MountPoint $env:SystemDrive)."
        "ProtectionStatus}catch{''}", timeout=20)
    return out or None


def build_security_report():
    L = [build_defender_status(), ""]
    fw = firewall_status()
    if fw:
        bits = ", ".join(f"{k} {'ON' if v else 'OFF'}" for k, v in fw.items())
        L.append(f"Firewall:  {bits}")
    else:
        L.append("Firewall:  status unavailable")
    bl = bitlocker_status()
    if bl:
        nice = {"On": "ON (encrypted)", "Off": "OFF (not encrypted)",
                "Unknown": "unknown"}.get(bl, bl)
        L.append(f"BitLocker (system drive):  {nice}")
    else:
        L.append("BitLocker:  unavailable (needs admin to read)")
    pu = pending_updates()
    if pu is None:
        L.append("Windows updates:  couldn't check right now")
    elif pu == 0:
        L.append("Windows updates:  up to date")
    else:
        L.append(f"Windows updates:  {pu} pending — install them for security")
    return "\n".join(L)


@owner_only
async def cmd_security(update, context):
    await update.message.reply_text("Checking security posture...")
    text = await asyncio.to_thread(build_security_report)
    await update.message.reply_text(text)


@owner_only
async def cmd_scan(update, context):
    arg = context.args[0].lower() if context.args else "quick"
    if arg == "full":
        ok = await asyncio.to_thread(start_full_scan_detached)
        await update.message.reply_text(
            "Full scan started in the background. It can take a long time; "
            "I'll alert you here if Defender finds anything." if ok
            else "Couldn't start a full scan (try running the bot as admin).")
        return
    if arg == "quick":
        await update.message.reply_text(
            "Running a Microsoft Defender quick scan... (usually a few minutes)")
        rc = await asyncio.to_thread(run_scan, "QuickScan", None, 1800)
    else:
        path = " ".join(context.args)
        await update.message.reply_text(f"Scanning {path} with Defender...")
        rc = await asyncio.to_thread(run_scan, "CustomScan", path, 1800)
    if rc == -2:
        await update.message.reply_text("Scan timed out.")
        return
    if rc != 0:
        await update.message.reply_text(
            "Couldn't complete the scan. Defender may be unavailable, the path "
            "may be wrong, or the bot may need to run as administrator.")
        return
    threats = await asyncio.to_thread(build_threats)
    await update.message.reply_text("Scan complete. ✅\n\n" + threats)


@owner_only
async def cmd_threats(update, context):
    await update.message.reply_text(await asyncio.to_thread(build_threats))


@owner_only
async def cmd_defupdate(update, context):
    await update.message.reply_text("Updating virus definitions...")
    rc, msg = await asyncio.to_thread(update_signatures)
    if rc == 0:
        d = await asyncio.to_thread(defender_status_raw)
        ver = d.get("sig", "?") if d else "?"
        await update.message.reply_text(f"Definitions updated. Now at v{ver}.")
    else:
        await update.message.reply_text(
            "Couldn't update definitions (may need admin).\n" + (msg[:300] or ""))


@owner_only
async def cmd_protect(update, context):
    ok, err = await asyncio.to_thread(enable_realtime)
    if ok:
        await update.message.reply_text("Real-time protection is ON.")
    else:
        await update.message.reply_text(
            "Couldn't change real-time protection. This usually needs the bot "
            "to run as administrator (and Tamper Protection may block it).\n"
            + (err[:300] or ""))


@owner_only
async def cmd_clean(update, context):
    await update.message.reply_text("Asking Defender to remove active threats...")
    rc, msg = await asyncio.to_thread(remove_threats)
    if rc == 0:
        await update.message.reply_text(
            "Remediation finished.\n\n" + await asyncio.to_thread(build_threats))
    else:
        await update.message.reply_text(
            "Couldn't remove threats (may need admin).\n" + (msg[:300] or ""))


@owner_only
async def cmd_firewall(update, context):
    arg = context.args[0].lower() if context.args else "status"
    if arg == "status":
        fw = await asyncio.to_thread(firewall_status)
        if not fw:
            await update.message.reply_text("Firewall status unavailable.")
            return
        bits = "\n".join(f"  {k}:  {'ON' if v else 'OFF'}"
                         for k, v in fw.items())
        await update.message.reply_text("Windows Firewall\n" + bits)
        return
    if arg in ("on", "enable"):
        ok, err = await asyncio.to_thread(firewall_set, True)
        await update.message.reply_text(
            "Firewall turned ON for all profiles." if ok
            else "Couldn't enable the firewall (needs admin).\n" + (err[:300] or ""))
        return
    if arg in ("off", "disable"):
        ok, err = await asyncio.to_thread(firewall_set, False)
        await update.message.reply_text(
            "⚠️ Firewall turned OFF for all profiles. Your machine is "
            "less protected — send /firewall on to re-enable it." if ok
            else "Couldn't disable the firewall (needs admin).\n" + (err[:300] or ""))
        return
    await update.message.reply_text("Usage: /firewall [status|on|off]")


async def threat_watch_job(context: ContextTypes.DEFAULT_TYPE):
    """Alert the owner when Defender finds something, or when real-time
    protection is switched off."""
    d = await asyncio.to_thread(defender_status_raw)
    if d is not None:
        rtp = bool(d.get("rtp"))
        if not rtp and not context.bot_data.get("rtp_warned"):
            await context.bot.send_message(
                config.CHAT_ID,
                "⚠️ Microsoft Defender real-time protection is OFF.\n"
                "Send /protect to turn it back on.")
            context.bot_data["rtp_warned"] = True
        elif rtp:
            context.bot_data["rtp_warned"] = False

    # newest detection time; alert if it moved since we last looked
    latest = await asyncio.to_thread(
        lambda: _powershell(
            "$d=Get-MpThreatDetection | Sort-Object InitialDetectionTime "
            "-Descending | Select-Object -First 1; "
            "if($d){$d.InitialDetectionTime.ToString('o')}", timeout=30))
    state = _load_state()
    seen = state.get("last_threat_seen")
    if latest and latest != seen:
        if seen is not None:        # don't alert on the very first baseline
            threats = await asyncio.to_thread(build_threats)
            await context.bot.send_message(
                config.CHAT_ID,
                "\U0001f6a8 Microsoft Defender detected a threat!\n\n" + threats)
        state["last_threat_seen"] = latest
        _save_state(state)


_CTRL_HANDLER = None      # must stay referenced or it gets collected


def install_shutdown_guard():
    """Tell Telegram when Windows starts shutting this laptop down.

    Windows delivers CTRL_SHUTDOWN_EVENT to console programs and then gives
    them only a few seconds, so this sends one synchronous message and gets
    out of the way. It cannot veto the shutdown -- see the README for why.
    """
    global _CTRL_HANDLER
    if os.name != "nt" or not config.CHAT_ID:
        return
    CTRL_LOGOFF, CTRL_SHUTDOWN = 5, 6

    def handler(event):
        if event in (CTRL_LOGOFF, CTRL_SHUTDOWN):
            what = "Log-off" if event == CTRL_LOGOFF else "Shutdown"
            _send_now(f"{what} started on this laptop at "
                      f"{datetime.now():%Y-%m-%d %H:%M:%S}.\n"
                      "This was started at the machine, not from Telegram.")
        return False        # let Windows carry on

    try:
        _CTRL_HANDLER = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, True)
        print("Shutdown guard armed.")
    except Exception as e:
        print("Could not arm shutdown guard:", e)


# --------------------------- lifecycle -----------------------------

async def login_snapshot(app):
    """On startup, send a screen grab and a webcam still of who's here."""
    try:
        shot = await asyncio.to_thread(grab_screenshot)
        try:
            with open(shot, "rb") as f:
                await app.bot.send_photo(config.CHAT_ID, f,
                                         caption="Screen at startup")
        finally:
            os.remove(shot)
    except Exception as e:
        print("Startup screenshot failed:", e)
    try:
        cam = await asyncio.to_thread(grab_webcam)
        if cam:
            try:
                with open(cam, "rb") as f:
                    await app.bot.send_photo(config.CHAT_ID, f,
                                             caption="Webcam at startup")
            finally:
                os.remove(cam)
        else:
            await app.bot.send_message(
                config.CHAT_ID, "Startup webcam photo unavailable "
                "(camera busy or opencv-python not installed).")
    except Exception as e:
        print("Startup webcam failed:", e)


BOT_COMMANDS = [
    ("status", "CPU, RAM, disk, battery"),
    ("battery", "Detailed battery / power"),
    ("uptime", "How long it's been on"),
    ("screenshot", "Photo of the screen"),
    ("photo", "Webcam photo"),
    ("clipboard", "Read the clipboard"),
    ("top", "Busiest processes"),
    ("apps", "What's running"),
    ("recent", "Newest downloaded files"),
    ("where", "Wi-Fi + rough location"),
    ("net", "Internet status"),
    ("weather", "Current weather [city]"),
    ("lock", "Lock the screen"),
    ("sleep", "Put the laptop to sleep"),
    ("notify", "Pop a message on screen"),
    ("speak", "Say something out loud"),
    ("mute", "Toggle mute"),
    ("volup", "Volume up"),
    ("voldown", "Volume down"),
    ("kill", "Close an app by name"),
    ("shutdown", "Shut down (confirms)"),
    ("abort", "Cancel a shutdown"),
    ("security", "Defender + firewall + BitLocker"),
    ("scan", "Antivirus scan [quick|full|path]"),
    ("threats", "Threats Defender found"),
    ("clean", "Remove active threats"),
    ("defupdate", "Update virus definitions"),
    ("protect", "Turn real-time protection on"),
    ("firewall", "Windows Firewall [status|on|off]"),
    ("ping", "Are you alive?"),
    ("help", "Full command list"),
]


async def on_startup(app):
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
    except Exception as e:
        print("Could not set command menu:", e)
    if config.CHAT_ID:
        try:
            await app.bot.send_message(config.CHAT_ID, "Laptop online - bot started.")
        except Exception as e:
            print("Could not send startup message:", e)
        if getattr(config, "LOGIN_SNAPSHOT", False):
            await login_snapshot(app)

    # start watching the folder (only if it exists and we know where to send)
    if config.CHAT_ID and os.path.isdir(config.WATCH_FOLDER):
        loop = asyncio.get_running_loop()
        observer = Observer()
        observer.schedule(NewFileHandler(loop, app.bot), config.WATCH_FOLDER,
                          recursive=False)
        observer.start()
        app.bot_data["observer"] = observer
        print("Watching folder:", config.WATCH_FOLDER)


async def on_shutdown(app):
    obs = app.bot_data.get("observer")
    if obs:
        obs.stop()
        obs.join(timeout=2)


def main():
    # (`--setup` is handled at the top of the file, before config loads.)
    if not config.BOT_TOKEN or "PASTE" in config.BOT_TOKEN:
        raise SystemExit(
            "This bot isn't set up yet.\n"
            "Run the guided setup:   python monitor_bot.py --setup\n"
            "(or set BOT_TOKEN in config.py manually - get it from @BotFather).")

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("photo", cmd_photo))
    app.add_handler(CommandHandler("disk", cmd_disk))
    app.add_handler(CommandHandler("net", cmd_net))
    app.add_handler(CommandHandler("where", cmd_where))
    app.add_handler(CommandHandler("apps", cmd_apps))
    app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    app.add_handler(CommandHandler("abort", cmd_abort))
    # new feature commands
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("uptime", cmd_uptime))
    app.add_handler(CommandHandler("battery", cmd_battery))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("clipboard", cmd_clipboard))
    app.add_handler(CommandHandler("notify", cmd_notify))
    # block=False: slow commands run alongside others instead of making
    # every later command (including /abort) queue behind them.
    app.add_handler(CommandHandler("speak", cmd_speak, block=False))
    app.add_handler(CommandHandler("weather", cmd_weather, block=False))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("volup", cmd_volup))
    app.add_handler(CommandHandler("voldown", cmd_voldown))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("ping", cmd_ping))
    # security / antivirus (Microsoft Defender)
    app.add_handler(CommandHandler("security", cmd_security, block=False))
    app.add_handler(CommandHandler("scan", cmd_scan, block=False))
    app.add_handler(CommandHandler("threats", cmd_threats, block=False))
    app.add_handler(CommandHandler("defupdate", cmd_defupdate, block=False))
    app.add_handler(CommandHandler("protect", cmd_protect, block=False))
    app.add_handler(CommandHandler("clean", cmd_clean, block=False))
    app.add_handler(CommandHandler("firewall", cmd_firewall, block=False))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(CommandHandler("myid", cmd_myid))

    if config.CHAT_ID:
        app.job_queue.run_repeating(check_internet,
                                    interval=config.NET_CHECK_INTERVAL, first=10)
        if getattr(config, "STATUS_INTERVAL", 0):
            app.job_queue.run_repeating(hourly_report,
                                        interval=config.STATUS_INTERVAL,
                                        first=getattr(config, "STATUS_FIRST", 30))
            print(f"Status report every {config.STATUS_INTERVAL}s")
        if getattr(config, "APP_REPORT_INTERVAL", 0):
            app.job_queue.run_repeating(app_report_job,
                                        interval=config.APP_REPORT_INTERVAL,
                                        first=90)
            print(f"App report every {config.APP_REPORT_INTERVAL}s")
        threat_interval = getattr(config, "THREAT_CHECK_INTERVAL", 1800)
        if threat_interval:
            app.job_queue.run_repeating(threat_watch_job,
                                        interval=threat_interval, first=45)
            print(f"Defender threat watch every {threat_interval}s")
    install_shutdown_guard()

    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
