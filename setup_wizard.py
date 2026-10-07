"""
Setup Wizard for the Laptop Monitor Bot.

A friendly, guided first-run setup so a non-technical user can get the bot
working without editing any Python by hand. It:

  1. Walks you through creating a bot with @BotFather.
  2. Takes your bot token and checks it really works (Telegram getMe).
  3. Auto-detects your chat id - you just send your bot a message.
  4. Writes config.py for you (preserving all the other settings).
  5. Optionally sets the bot to start automatically with Windows.

Uses only the Python standard library, so it runs before you've installed
anything else.

Run it:   python setup_wizard.py
"""

import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# In a PyInstaller build, __file__ points inside the temporary bundle folder.
# The user's config.py must live beside the .exe instead, so it survives
# restarts and can be edited; the template ships inside the bundle.
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
    BUNDLE = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = BUNDLE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.py")
EXAMPLE = next((p for p in (os.path.join(HERE, "config.example.py"),
                            os.path.join(BUNDLE, "config.example.py"))
                if os.path.exists(p)),
               os.path.join(HERE, "config.example.py"))
API = "https://api.telegram.org/bot{token}/{method}"


# --------------------------- small UI helpers ---------------------------

def line(ch="-", n=60):
    print(ch * n)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(1)
    return val or (default or "")


def yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({d})").lower()
    if not val:
        return default
    return val.startswith("y")


# --------------------------- Telegram calls ---------------------------

def tg_call(token, method, params=None, timeout=15):
    """Call a Telegram Bot API method. Returns the parsed JSON or None."""
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(url, data if params else None,
                                    timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return None
    except Exception:
        return None


def validate_token(token):
    """Return the bot's username if the token is valid, else None."""
    res = tg_call(token, "getMe")
    if res and res.get("ok"):
        return res["result"].get("username")
    return None


def _skip_queued_updates(token):
    """Return an offset just past every update already waiting for the bot.

    Anyone can message a bot, so anything queued before setup started must
    never be mistaken for the owner. Passing this offset to getUpdates also
    tells Telegram to drop those old updates.
    """
    res = tg_call(token, "getUpdates", {"offset": -1, "timeout": 0})
    if res and res.get("ok") and res.get("result"):
        return res["result"][-1]["update_id"] + 1
    return None


def detect_chat_id(token, attempts=40, delay=3):
    """Link the bot to its owner, securely.

    The chat id decides who can take screenshots and control the laptop, so
    it is only accepted from a PRIVATE chat that sends a fresh one-time code
    shown here on screen - proof the sender is the person running setup.
    Messages from groups, channels, or sent before setup began are ignored,
    and the owner confirms the detected account before it is saved.
    Returns the chat id as a string, or None.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    offset = _skip_queued_updates(token)
    print("\nOpen Telegram, find your bot, and send it this code:\n")
    print(f"        {code}\n")
    print("(Send it in a private chat with the bot - not in a group.)")
    print("Waiting for the code", end="", flush=True)
    for _ in range(attempts):
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        res = tg_call(token, "getUpdates", params)
        if res and res.get("ok"):
            for upd in res["result"]:
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                chat = msg.get("chat") or {}
                if chat.get("type") != "private":
                    continue
                if (msg.get("text") or "").strip() != code:
                    continue
                print(" got it!")
                name = chat.get("username") or chat.get("first_name") or "?"
                if yesno(f"Code received from Telegram account '{name}'. "
                         "Is that you?", default=True):
                    tg_call(token, "getUpdates", {"offset": offset, "timeout": 0})
                    return str(chat["id"])
                print("Ignored. Waiting for the code from your own account",
                      end="", flush=True)
        print(".", end="", flush=True)
        time.sleep(delay)
    print("\nDidn't receive the code in time.")
    return None


# --------------------------- writing config ---------------------------

def write_config(token, chat_id):
    """Write config.py from the template, filling in token and chat id,
    and preserving any other settings the user already had."""
    src = CONFIG if os.path.exists(CONFIG) else EXAMPLE
    if not os.path.exists(src):
        # fall back to a minimal file if neither template is present
        text = (f'import os\n\nBOT_TOKEN = "{token}"\nCHAT_ID = "{chat_id}"\n'
                'WATCH_FOLDER = os.path.join(os.path.expanduser("~"), '
                '"Downloads")\nNET_CHECK_INTERVAL = 60\nSTATUS_INTERVAL = 3600\n'
                'STATUS_FIRST = 30\nAPP_REPORT_INTERVAL = 18000\n'
                'SHUTDOWN_DELAY = 30\nLOGIN_SNAPSHOT = True\nCAMERA_INDEX = 0\n'
                'CAMERA_WARMUP = 8\nLOCATION_ENABLED = True\n')
    else:
        with open(src, encoding="utf-8") as f:
            text = f.read()

    def repl(name, value, body):
        pattern = re.compile(rf'^(\s*){name}\s*=.*$', re.MULTILINE)
        line_ = f'{name} = "{value}"'
        if pattern.search(body):
            return pattern.sub(lambda m: m.group(1) + line_, body, count=1)
        return body + f"\n{line_}\n"

    text = repl("BOT_TOKEN", token, text)
    text = repl("CHAT_ID", chat_id, text)

    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(text)
    return CONFIG


def offer_autostart():
    """Add the bot (and companion) to Windows startup via the registry."""
    if os.name != "nt":
        print("(Auto-start is Windows-only; skipping.)")
        return
    if not yesno("Start the bot automatically when you log in to Windows?",
                 default=False):
        return
    try:
        import winreg
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}"'          # the packaged MonitorBot.exe
        else:
            pyw = sys.executable
            # prefer pythonw.exe so no console window pops up
            cand = os.path.join(os.path.dirname(pyw), "pythonw.exe")
            if os.path.exists(cand):
                pyw = cand
            cmd = f'"{pyw}" "{os.path.join(HERE, "monitor_bot.py")}"'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
            winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "LaptopMonitorBot", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print("Done - the bot will start with Windows.")
    except Exception as e:
        print("Couldn't set auto-start:", e)


# ------------------------------- main -------------------------------

def main():
    line("=")
    print("  Laptop Monitor Bot - Setup Wizard")
    line("=")
    print(
        "\nThis gets your bot talking to you on Telegram. It takes about a\n"
        "minute. You'll need the Telegram app on your phone or desktop.\n")

    print("STEP 1 - Create your bot")
    line()
    print("1. Open Telegram and search for:  @BotFather")
    print("2. Send it:  /newbot")
    print("3. Pick a name, then a username that ends in 'bot'.")
    print("4. BotFather replies with a token like 123456:ABC-DEF...\n")

    token = ""
    while True:
        token = ask("Paste your bot token here")
        if not token:
            print("A token is required. Copy it from BotFather.")
            continue
        print("Checking the token...", end=" ", flush=True)
        username = validate_token(token)
        if username:
            print(f"works! Your bot is @{username}.")
            break
        print("that didn't work.")
        if not yesno("Try a different token?", default=True):
            print("Setup cancelled.")
            return

    print("\nSTEP 2 - Link it to you")
    line()
    chat_id = detect_chat_id(token)
    if not chat_id:
        print("\nNo problem - you can finish this later. Start the bot with")
        print("  python monitor_bot.py")
        print("send it /myid from your own account, and paste the number into")
        print("config.py as CHAT_ID. Only paste an id you got that way.")
        chat_id = ask("Or, if you know your chat id, paste it now (optional)")

    print("\nSTEP 3 - Save your settings")
    line()
    path = write_config(token, chat_id)
    print(f"Wrote {path}")
    if chat_id:
        tg_call(token, "sendMessage",
                {"chat_id": chat_id,
                 "text": "Setup complete! Your Laptop Monitor Bot is ready. "
                         "Send /help to see what it can do."})
        print("Sent a confirmation message to your Telegram.")

    print("\nSTEP 4 - Finishing touches")
    line()
    offer_autostart()

    line("=")
    print("All set! Start the bot any time with:\n    python monitor_bot.py")
    if chat_id:
        print("Then send it  /help  in Telegram.")
    line("=")


if __name__ == "__main__":
    main()
