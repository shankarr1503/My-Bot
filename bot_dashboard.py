"""
Laptop Monitor Bot - Dashboard
==============================

A friendly control panel for the Monitor Bot. No command line, no editing
Python: paste your Telegram bot token, link your account with a one-time
code, tweak settings with sliders and switches, and start/stop the bot with
a button - all while watching its live log and your laptop's vital signs.

Tabs
----
  * Connect   - bot token (with a "Test" check) and a secure "Link my
                account" flow; shows whether you're ready to go.
  * Control   - Start / Stop the bot, a status light, and a live log.
  * Settings  - every interval and toggle the bot supports.
  * System    - live CPU / RAM / disk / battery and uptime.
  * Commands  - the full list of what you can send the bot in Telegram.
  * About     - version and links.

Everything is saved to config.py, which the bot reads. The dashboard uses
only the standard library plus psutil (already a bot dependency), so it
packages exactly like the rest of the suite.

Run:            python bot_dashboard.py
Headless check: python bot_dashboard.py --selftest
"""

import os
import queue
import sys
import threading
import time

# --- where we live, and where config.py should go ---------------------------
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
    BUNDLE = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = BUNDLE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.py")


def _example_path():
    for p in (os.path.join(HERE, "config.example.py"),
              os.path.join(BUNDLE, "config.example.py")):
        if os.path.exists(p):
            return p
    return None


APP_TITLE = "Laptop Monitor Bot - Dashboard"
VERSION = "1.0.0"

# Every configurable value: key, python type, default, and a friendly label.
# Order controls how they appear on the Settings tab.
SETTINGS = [
    ("WATCH_FOLDER", "path", "", "Folder to watch for new files"),
    ("NET_CHECK_INTERVAL", "int", 60, "Check internet every (seconds)"),
    ("STATUS_INTERVAL", "int", 3600, "Status report every (seconds, 0 = off)"),
    ("STATUS_FIRST", "int", 30, "First status report after (seconds)"),
    ("APP_REPORT_INTERVAL", "int", 18000, "App report every (seconds, 0 = off)"),
    ("THREAT_CHECK_INTERVAL", "int", 1800, "Defender check every (seconds, 0 = off)"),
    ("SHUTDOWN_DELAY", "int", 30, "Shutdown countdown (seconds)"),
    ("CAMERA_INDEX", "int", 0, "Webcam index (0 = built-in)"),
    ("CAMERA_WARMUP", "int", 8, "Webcam warm-up frames"),
    ("LOGIN_SNAPSHOT", "bool", True, "Send screen + webcam when the bot starts"),
    ("LOCATION_ENABLED", "bool", True, "Include approximate location in reports"),
]
_DEF = {k: d for (k, _t, d, _l) in SETTINGS}
_TYPE = {k: t for (k, t, _d, _l) in SETTINGS}


# ============================================================================
#  config.py read / write  (stdlib only)
# ============================================================================

def _default_watch_folder():
    return os.path.join(os.path.expanduser("~"), "Downloads")


def read_config():
    """Load the current values from config.py (or the example template).
    Returns a dict including BOT_TOKEN and CHAT_ID. Missing/blank -> defaults."""
    import importlib.util
    values = {"BOT_TOKEN": "", "CHAT_ID": ""}
    values.update(_DEF)
    values["WATCH_FOLDER"] = _default_watch_folder()

    src = CONFIG_PATH if os.path.exists(CONFIG_PATH) else _example_path()
    if src and os.path.exists(src):
        try:
            spec = importlib.util.spec_from_file_location("_cfg_read", src)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for key in list(values):
                if hasattr(mod, key):
                    values[key] = getattr(mod, key)
        except Exception:
            pass
    # a template token counts as "not set"
    if "PASTE" in str(values.get("BOT_TOKEN", "")):
        values["BOT_TOKEN"] = ""
    if not values.get("WATCH_FOLDER"):
        values["WATCH_FOLDER"] = _default_watch_folder()
    return values


def write_config(values):
    """Write config.py from the template, filling every key with repr() so
    paths, quotes and backslashes are always valid Python. Comments in the
    template are preserved."""
    src = _example_path()
    if src and os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            text = f.read()
    else:
        text = ("import os\n\nBOT_TOKEN = \"\"\nCHAT_ID = \"\"\n"
                "WATCH_FOLDER = \"\"\nNET_CHECK_INTERVAL = 60\n"
                "STATUS_INTERVAL = 3600\nSTATUS_FIRST = 30\n"
                "APP_REPORT_INTERVAL = 18000\nTHREAT_CHECK_INTERVAL = 1800\n"
                "SHUTDOWN_DELAY = 30\nLOGIN_SNAPSHOT = True\nCAMERA_INDEX = 0\n"
                "CAMERA_WARMUP = 8\nLOCATION_ENABLED = True\n")

    import re
    for key in ["BOT_TOKEN", "CHAT_ID"] + [k for (k, *_r) in SETTINGS]:
        if key not in values:
            continue
        line = f"{key} = {values[key]!r}"
        pattern = re.compile(rf'^(\s*){re.escape(key)}\s*=.*$', re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda m, ln=line: m.group(1) + ln, text, count=1)
        else:
            text += f"\n{line}\n"

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    return CONFIG_PATH


def bot_command():
    """Return (argv, cwd) to launch the bot.

    In the packaged app the dashboard and the bot are the same executable, so
    we just re-run ourselves with --bot. From source we run monitor_bot.py.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--bot"], HERE
    script = os.path.join(HERE, "monitor_bot.py")
    return [sys.executable, script], HERE


# ============================================================================
#  Headless self-test
# ============================================================================

def selftest():
    import tempfile
    global CONFIG_PATH
    CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config.py")
    v = read_config()
    assert v["NET_CHECK_INTERVAL"] == 60
    v["BOT_TOKEN"] = "123:ABCDEF"
    v["CHAT_ID"] = "42"
    v["STATUS_INTERVAL"] = 0
    v["LOGIN_SNAPSHOT"] = False
    v["WATCH_FOLDER"] = r"C:\Users\me\Downloads"
    write_config(v)
    back = read_config()
    assert back["BOT_TOKEN"] == "123:ABCDEF", back["BOT_TOKEN"]
    assert back["CHAT_ID"] == "42"
    assert back["STATUS_INTERVAL"] == 0
    assert back["LOGIN_SNAPSHOT"] is False
    assert back["WATCH_FOLDER"] == r"C:\Users\me\Downloads", back["WATCH_FOLDER"]
    argv, cwd = bot_command()
    print("config round-trip OK (token, chat id, ints, bools, backslash path)")
    print("bot launch:", argv[0], "...")
    print("Dashboard self-test passed.")


# ============================================================================
#  The GUI
# ============================================================================

def run_app():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    # import the bot's Telegram helpers (stdlib-based, no side effects on import)
    try:
        import setup_wizard as wiz
    except Exception:
        wiz = None

    import random
    import urllib.request

    try:
        import psutil
    except Exception:
        psutil = None

    OK = "#1f9d55"
    BAD = "#d64545"
    MUTE = "#667085"

    class Dashboard:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title(APP_TITLE)
            self.root.geometry("760x620")
            self.root.minsize(680, 560)

            self.proc = None
            self.log_q = queue.Queue()
            self.detect_thread = None
            self.detect_stop = threading.Event()

            cfg = read_config()
            # tk variables for every field
            self.var_token = tk.StringVar(value=cfg["BOT_TOKEN"])
            self.var_chat = tk.StringVar(value=str(cfg["CHAT_ID"] or ""))
            self.vars = {}
            for key, typ, default, _label in SETTINGS:
                if typ == "bool":
                    self.vars[key] = tk.BooleanVar(value=bool(cfg[key]))
                elif typ == "int":
                    self.vars[key] = tk.IntVar(value=int(cfg[key]))
                else:
                    self.vars[key] = tk.StringVar(value=str(cfg[key]))

            self._build_style()
            self._build_header()
            nb = ttk.Notebook(self.root)
            self.nb = nb
            nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
            self._tab_connect(nb)
            self._tab_control(nb)
            self._tab_settings(nb)
            self._tab_system(nb)
            self._tab_commands(nb)
            self._tab_about(nb)

            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.refresh_status()
            self._pump_log()
            self._refresh_system()

        # ---------- chrome ----------
        def _build_style(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("TNotebook.Tab", padding=(14, 7))
            style.configure("Big.TButton", padding=(16, 10), font=("Segoe UI", 11, "bold"))
            style.configure("Card.TLabelframe", padding=12)

        def _build_header(self):
            bar = tk.Frame(self.root, bg="#6366f1")
            bar.pack(fill="x")
            tk.Label(bar, text="  🤖  Laptop Monitor Bot", bg="#6366f1",
                     fg="white", font=("Segoe UI", 15, "bold")).pack(
                side="left", pady=10, padx=6)
            self.hdr_status = tk.Label(bar, text="●  checking...", bg="#6366f1",
                                       fg="white", font=("Segoe UI", 10))
            self.hdr_status.pack(side="right", padx=14)

        # ---------- Connect tab ----------
        def _tab_connect(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  Connect  ")
            pad = {"padx": 12, "pady": 6}

            intro = ("1. In Telegram, message @BotFather, send /newbot, and copy "
                     "the token it gives you.\n"
                     "2. Paste the token below and press Test.\n"
                     "3. Press \"Link my account\" and send your bot the code shown.")
            tk.Label(f, text=intro, justify="left", fg=MUTE).grid(
                row=0, column=0, columnspan=3, sticky="w", **pad)

            tk.Label(f, text="Bot token:").grid(row=1, column=0, sticky="e", **pad)
            e = ttk.Entry(f, textvariable=self.var_token, width=46, show="•")
            e.grid(row=1, column=1, sticky="we", **pad)
            self.token_entry = e
            btns = ttk.Frame(f)
            btns.grid(row=1, column=2, sticky="w")
            ttk.Button(btns, text="Show", width=6,
                       command=self._toggle_token).pack(side="left", padx=2)
            ttk.Button(btns, text="Test", width=6,
                       command=self.test_token).pack(side="left", padx=2)
            self.token_status = tk.Label(f, text="", fg=MUTE)
            self.token_status.grid(row=2, column=1, sticky="w", padx=12)

            tk.Label(f, text="Your chat id:").grid(row=3, column=0, sticky="e", **pad)
            ttk.Entry(f, textvariable=self.var_chat, width=24).grid(
                row=3, column=1, sticky="w", **pad)
            ttk.Button(f, text="Link my account",
                       command=self.link_account).grid(row=3, column=2, sticky="w")
            self.link_status = tk.Label(f, text="", fg=MUTE, justify="left",
                                        wraplength=420)
            self.link_status.grid(row=4, column=1, columnspan=2, sticky="w", padx=12)

            ttk.Separator(f, orient="horizontal").grid(
                row=5, column=0, columnspan=3, sticky="we", pady=10, padx=12)
            ttk.Button(f, text="Save", style="Big.TButton",
                       command=self.save_all).grid(row=6, column=1, sticky="w", padx=12)
            self.connect_hint = tk.Label(
                f, text="Your token stays on this PC, in config.py.", fg=MUTE)
            self.connect_hint.grid(row=6, column=2, sticky="w")
            f.columnconfigure(1, weight=1)

        def _toggle_token(self):
            self.token_entry.config(show="" if self.token_entry.cget("show") else "•")

        # ---------- Control tab ----------
        def _tab_control(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  Control  ")

            top = ttk.Frame(f)
            top.pack(fill="x", padx=12, pady=10)
            self.btn_start = ttk.Button(top, text="▶  Start bot",
                                        style="Big.TButton", command=self.start_bot)
            self.btn_start.pack(side="left")
            self.btn_stop = ttk.Button(top, text="■  Stop bot",
                                       style="Big.TButton", command=self.stop_bot,
                                       state="disabled")
            self.btn_stop.pack(side="left", padx=8)
            self.run_light = tk.Label(top, text="●  Stopped", fg=BAD,
                                      font=("Segoe UI", 11, "bold"))
            self.run_light.pack(side="right")

            lf = ttk.Labelframe(f, text="Live log")
            lf.pack(fill="both", expand=True, padx=12, pady=(0, 6))
            self.log = tk.Text(lf, height=16, bg="#0f172a", fg="#e2e8f0",
                               insertbackground="#e2e8f0", font=("Consolas", 9),
                               wrap="word", state="disabled")
            sb = ttk.Scrollbar(lf, command=self.log.yview)
            self.log.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.log.pack(side="left", fill="both", expand=True)

            row = ttk.Frame(f)
            row.pack(fill="x", padx=12, pady=(0, 10))
            ttk.Button(row, text="Clear log", command=self.clear_log).pack(side="left")
            self.autostart_note = tk.Label(
                row, text="Tip: send /help to your bot in Telegram once it's running.",
                fg=MUTE)
            self.autostart_note.pack(side="right")

        # ---------- Settings tab ----------
        def _tab_settings(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  Settings  ")
            canvas_pad = {"padx": 12, "pady": 5}
            r = 0
            for key, typ, default, label in SETTINGS:
                tk.Label(f, text=label + ":").grid(row=r, column=0, sticky="e",
                                                   **canvas_pad)
                if typ == "bool":
                    ttk.Checkbutton(f, variable=self.vars[key]).grid(
                        row=r, column=1, sticky="w", **canvas_pad)
                elif typ == "path":
                    e = ttk.Entry(f, textvariable=self.vars[key], width=40)
                    e.grid(row=r, column=1, sticky="we", **canvas_pad)
                    ttk.Button(f, text="Browse...",
                               command=lambda k=key: self._browse(k)).grid(
                        row=r, column=2, sticky="w")
                else:
                    ttk.Spinbox(f, from_=0, to=999999, width=12,
                                textvariable=self.vars[key]).grid(
                        row=r, column=1, sticky="w", **canvas_pad)
                r += 1
            ttk.Separator(f, orient="horizontal").grid(
                row=r, column=0, columnspan=3, sticky="we", pady=10, padx=12)
            ttk.Button(f, text="Save settings", style="Big.TButton",
                       command=self.save_all).grid(row=r + 1, column=1, sticky="w",
                                                   padx=12, pady=6)
            tk.Label(f, text="Changes apply the next time the bot starts.",
                     fg=MUTE).grid(row=r + 1, column=2, sticky="w")
            f.columnconfigure(1, weight=1)

        def _browse(self, key):
            d = filedialog.askdirectory(initialdir=self.vars[key].get() or HERE)
            if d:
                self.vars[key].set(d)

        # ---------- System tab ----------
        def _tab_system(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  System  ")
            self.meters = {}
            if psutil is None:
                tk.Label(f, text="psutil isn't installed, so live stats are "
                         "unavailable.", fg=MUTE).pack(padx=16, pady=16)
                return
            for name in ("CPU", "Memory", "Disk C:", "Battery"):
                row = ttk.Frame(f)
                row.pack(fill="x", padx=16, pady=10)
                tk.Label(row, text=name, width=10, anchor="w",
                         font=("Segoe UI", 10, "bold")).pack(side="left")
                bar = ttk.Progressbar(row, length=420, maximum=100)
                bar.pack(side="left", padx=10)
                val = tk.Label(row, text="--", width=18, anchor="w", fg=MUTE)
                val.pack(side="left")
                self.meters[name] = (bar, val)
            self.uptime_lbl = tk.Label(f, text="Uptime: --", fg=MUTE)
            self.uptime_lbl.pack(anchor="w", padx=16, pady=8)

        # ---------- Commands tab ----------
        def _tab_commands(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  Commands  ")
            rows = [
                ("/status", "CPU, RAM, disk, battery"),
                ("/battery", "Detailed battery / power"),
                ("/uptime", "How long it's been on"),
                ("/screenshot", "Photo of the screen"),
                ("/photo", "Webcam photo"),
                ("/clipboard", "Read the clipboard"),
                ("/top", "Busiest processes"),
                ("/apps", "What's running"),
                ("/recent", "Newest downloaded files"),
                ("/where", "Wi-Fi + rough location"),
                ("/weather [city]", "Current weather"),
                ("/lock", "Lock the screen"),
                ("/sleep", "Put the laptop to sleep"),
                ("/notify <msg>", "Pop a message on screen"),
                ("/speak <msg>", "Say something out loud"),
                ("/mute  /volup  /voldown", "Volume control"),
                ("/kill <app>", "Close an app by name"),
                ("/shutdown  /abort", "Shut down (with confirm) / cancel"),
                ("/security", "Defender + firewall + BitLocker"),
                ("/scan [quick|full|path]", "Antivirus scan"),
                ("/threats  /clean", "Threats found / remove them"),
                ("/defupdate  /protect", "Update definitions / real-time on"),
                ("/firewall [on|off]", "Windows Firewall"),
                ("/help", "Full command list"),
            ]
            txt = tk.Text(f, wrap="none", font=("Consolas", 10), bg="#f8fafc")
            txt.pack(fill="both", expand=True, padx=12, pady=12)
            for cmd, desc in rows:
                txt.insert("end", f"{cmd:<28} {desc}\n")
            txt.config(state="disabled")

        # ---------- About tab ----------
        def _tab_about(self, nb):
            f = ttk.Frame(nb)
            nb.add(f, text="  About  ")
            tk.Label(f, text="Laptop Monitor Bot - Dashboard",
                     font=("Segoe UI", 14, "bold")).pack(pady=(24, 4))
            tk.Label(f, text=f"Version {VERSION}", fg=MUTE).pack()
            tk.Label(f, text="Control your Windows laptop from Telegram:\n"
                     "status, screenshots, webcam, security scans and more.",
                     fg=MUTE, justify="center").pack(pady=12)
            tk.Label(f, text=f"Config file: {CONFIG_PATH}", fg=MUTE).pack(pady=4)

        # ===================== actions =====================
        def _collect(self):
            vals = {"BOT_TOKEN": self.var_token.get().strip(),
                    "CHAT_ID": self.var_chat.get().strip()}
            for key, typ, default, _label in SETTINGS:
                try:
                    if typ == "bool":
                        vals[key] = bool(self.vars[key].get())
                    elif typ == "int":
                        vals[key] = int(self.vars[key].get())
                    else:
                        vals[key] = str(self.vars[key].get())
                except Exception:
                    vals[key] = default
            return vals

        def save_all(self):
            vals = self._collect()
            try:
                path = write_config(vals)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Couldn't save config:\n{e}")
                return
            self.refresh_status()
            messagebox.showinfo(APP_TITLE, f"Saved to\n{path}")

        def test_token(self):
            token = self.var_token.get().strip()
            if not token:
                self.token_status.config(text="Enter a token first.", fg=BAD)
                return
            self.token_status.config(text="Checking...", fg=MUTE)
            self.root.update_idletasks()

            def work():
                name = wiz.validate_token(token) if wiz else None
                self.root.after(0, lambda: self._token_result(name))
            threading.Thread(target=work, daemon=True).start()

        def _token_result(self, name):
            if name:
                self.token_status.config(text=f"✓ Works - your bot is @{name}", fg=OK)
            else:
                self.token_status.config(
                    text="✗ That token didn't work.", fg=BAD)

        def link_account(self):
            if wiz is None:
                self.link_status.config(text="Setup helper unavailable.", fg=BAD)
                return
            token = self.var_token.get().strip()
            if not token:
                self.link_status.config(text="Enter and Test your token first.", fg=BAD)
                return
            if self.detect_thread and self.detect_thread.is_alive():
                return
            code = f"{random.randrange(1000000):06d}"
            self.link_status.config(
                text=f"Send this code to your bot in Telegram (private chat):\n"
                     f"        {code}\nWaiting for it...", fg=MUTE)
            self.detect_stop.clear()

            def work():
                try:
                    offset = wiz._skip_queued_updates(token)
                    for _ in range(40):
                        if self.detect_stop.is_set():
                            return
                        params = {"timeout": 0}
                        if offset is not None:
                            params["offset"] = offset
                        res = wiz.tg_call(token, "getUpdates", params)
                        if res and res.get("ok"):
                            for upd in res["result"]:
                                offset = upd["update_id"] + 1
                                msg = upd.get("message") or {}
                                chat = msg.get("chat") or {}
                                if (chat.get("type") == "private"
                                        and (msg.get("text") or "").strip() == code):
                                    cid = str(chat["id"])
                                    nm = chat.get("username") or chat.get(
                                        "first_name") or "you"
                                    self.root.after(
                                        0, lambda: self._linked(cid, nm))
                                    return
                        time.sleep(3)
                    self.root.after(0, lambda: self.link_status.config(
                        text="Didn't receive the code in time. Try again.", fg=BAD))
                except Exception as e:
                    self.root.after(0, lambda: self.link_status.config(
                        text=f"Couldn't link: {e}", fg=BAD))

            self.detect_thread = threading.Thread(target=work, daemon=True)
            self.detect_thread.start()

        def _linked(self, cid, name):
            self.var_chat.set(cid)
            self.link_status.config(text=f"✓ Linked to {name} (id {cid}). "
                                    "Press Save.", fg=OK)

        # ----- bot process -----
        def start_bot(self):
            if self.proc and self.proc.poll() is None:
                return
            vals = self._collect()
            if not vals["BOT_TOKEN"] or not vals["CHAT_ID"]:
                messagebox.showwarning(
                    APP_TITLE, "Set your bot token and link your account on the "
                    "Connect tab first (then Save).")
                return
            try:
                write_config(vals)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Couldn't save config:\n{e}")
                return
            import subprocess
            argv, cwd = bot_command()
            env = dict(os.environ)
            env["MONITORBOT_TOKEN"] = vals["BOT_TOKEN"]
            env["MONITORBOT_CHAT_ID"] = vals["CHAT_ID"]
            env["PYTHONUNBUFFERED"] = "1"
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self.proc = subprocess.Popen(
                    argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                    creationflags=flags)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Couldn't start the bot:\n{e}")
                return
            self._log(f"=== bot started ({os.path.basename(argv[0])}) ===")
            threading.Thread(target=self._reader, args=(self.proc,),
                             daemon=True).start()
            self.refresh_status()

        def _reader(self, proc):
            try:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    self.log_q.put(line.rstrip("\n"))
            except Exception:
                pass
            self.log_q.put("=== bot stopped ===")
            self.root.after(0, self.refresh_status)

        def stop_bot(self):
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            self.refresh_status()

        def _pump_log(self):
            try:
                while True:
                    self._log(self.log_q.get_nowait())
            except queue.Empty:
                pass
            self.root.after(150, self._pump_log)

        def _log(self, text):
            self.log.config(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.config(state="disabled")

        def clear_log(self):
            self.log.config(state="normal")
            self.log.delete("1.0", "end")
            self.log.config(state="disabled")

        # ----- status + system -----
        def refresh_status(self):
            running = bool(self.proc and self.proc.poll() is None)
            if running:
                self.run_light.config(text="●  Running", fg=OK)
                self.btn_start.config(state="disabled")
                self.btn_stop.config(state="normal")
            else:
                self.run_light.config(text="●  Stopped", fg=BAD)
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")

            cfg = read_config()
            ready = bool(cfg["BOT_TOKEN"] and cfg["CHAT_ID"])
            if running:
                self.hdr_status.config(text="●  bot running")
            elif ready:
                self.hdr_status.config(text="●  ready - press Start")
            else:
                self.hdr_status.config(text="●  not configured")

        def _refresh_system(self):
            if psutil is not None and getattr(self, "meters", None):
                try:
                    self._set_meter("CPU", psutil.cpu_percent(),
                                    f"{psutil.cpu_percent():.0f}%")
                    m = psutil.virtual_memory()
                    self._set_meter("Memory", m.percent, f"{m.percent:.0f}%")
                    d = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
                    self._set_meter("Disk C:", d.percent,
                                    f"{d.percent:.0f}%  ({d.free // 2**30} GB free)")
                    b = psutil.sensors_battery()
                    if b is not None:
                        plug = "charging" if b.power_plugged else "on battery"
                        self._set_meter("Battery", b.percent,
                                        f"{b.percent:.0f}%  ({plug})")
                    else:
                        self._set_meter("Battery", 0, "no battery")
                    boot = time.time() - psutil.boot_time()
                    h, rem = divmod(int(boot), 3600)
                    self.uptime_lbl.config(
                        text=f"Uptime: {h}h {rem // 60}m")
                except Exception:
                    pass
            self.root.after(2000, self._refresh_system)

        def _set_meter(self, name, pct, text):
            bar, lbl = self.meters[name]
            bar["value"] = max(0, min(100, pct))
            lbl.config(text=text)

        def on_close(self):
            self.detect_stop.set()
            if self.proc and self.proc.poll() is None:
                if not messagebox.askokcancel(
                        APP_TITLE, "The bot is running. Stop it and quit?"):
                    return
                self.stop_bot()
            self.root.destroy()

        def run(self):
            self.root.mainloop()

    Dashboard().run()


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    run_app()


if __name__ == "__main__":
    main()
