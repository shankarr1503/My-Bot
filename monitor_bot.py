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
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime

import psutil
from PIL import ImageGrab
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config


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
    "/status - CPU, RAM, disk, battery\n"
    "/screenshot - photo of the current screen\n"
    "/photo - webcam photo\n"
    "/disk - usage of every drive\n"
    "/net - internet status\n"
    "/where - Wi-Fi network + approximate location\n"
    "/apps - what is running, open and closed\n"
    "/shutdown - shut the laptop down (asks you to confirm)\n"
    "/abort - call off a shutdown\n"
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


async def on_startup(app):
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
    if not config.BOT_TOKEN or "PASTE" in config.BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN in config.py first (get it from @BotFather).")

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
    install_shutdown_guard()

    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
