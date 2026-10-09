# Companion Suite — Desktop Companion + Laptop Monitor Bot

A suite of Windows apps:

1. **Desktop Companion** (`desktop_companion.py`) — the flagship, store-ready
   app. A friendly animated pet with **nine characters**, a **system-tray
   icon**, a **settings window**, drag-anywhere with position memory, speech
   bubbles, a built-in **Pomodoro focus timer + break reminders**, and a
   **feed-and-play care system** with a **Catch-the-Treats mini-game**. Zero
   setup — just run it. This is the piece packaged for the **Microsoft Store**
   (see [`packaging/SUBMISSION.md`](packaging/SUBMISSION.md)).
2. **Monitor Bot** (`monitor_bot.py`) — a Telegram bot that reports system
   health and gives you 25+ remote commands (screenshots, webcam, lock, sleep,
   notify, speak, volume, clipboard, weather, kill apps, shutdown, and more).
3. **Anti-theft sentinel** (`antitheft_sentinel.py`) — alerts you on failed
   logins, armed from boot.

---

## Install on your Windows laptop

You have two ways to get Desktop Companion running. **Way 1 is the easiest.**

### Way 1 — One-click installer (runs from the code)

1. Install **Python 3.10+** from <https://www.python.org/downloads/> — on the
   first screen of the installer, **tick "Add Python to PATH"**.
2. Download this project (green **Code** button → **Download ZIP**) and unzip it.
3. Double-click **`install.bat`**.

That's it. It installs what's needed, puts a **Desktop Companion** shortcut on
your desktop, and starts the pet. Start it again any time from that shortcut
(or by double-clicking **`run_companion.bat`**).

### Way 2 — Download the ready-made app (no Python needed)

Every change is built into a real Windows `.exe` automatically.

**Best: from a Release** (a stable, public download):

1. Go to the repo's **Releases** page and open the latest version.
2. Download **`DesktopCompanion-windows.zip`**, unzip it, and double-click
   **`DesktopCompanion.exe`**.

**Or from a build run** (needs you to be **signed in to GitHub** with read
access to this repo):

1. **Actions** tab → open a **"Build Windows apps"** run **on the `main`
   branch** (pick a trusted, merged build — not a pull-request run, which can
   contain unreviewed changes).
2. Under **Artifacts**, download **`DesktopCompanion-windows`**, unzip it, and
   double-click **`DesktopCompanion.exe`**.

> The first time Windows SmartScreen may say "unknown publisher" because the
> app isn't code-signed yet (signing is part of the Microsoft Store step).
> Click **More info → Run anyway**. The Store build is signed by Microsoft and
> won't show this.

### For developers

```
pip install -r requirements.txt
python desktop_companion.py          # or: python desktop_companion.py cat
```
Right-click the pet (or its tray icon) for the menu; double-click it to chat;
drag it anywhere.

---

## Desktop Companion — features

| | |
|---|---|
| **9 characters** | Robot, Cat, Ghost, Slime, Duck, Fox, Penguin, Dino, Bunny — each with a name |
| **System tray** | Show / hide / settings / quit, even when the pet is hidden |
| **Settings window** | Pick pet, size, toggle features, timer lengths, start-with-Windows |
| **Drag & remember** | Move the pet anywhere; its spot is saved between runs |
| **Speech bubbles** | Friendly, encouraging one-liners |
| **Pet care** | Feed your pet and keep it happy; it gets hungry over time and shows its mood |
| **Catch-the-Treats mini-game** | A quick clicking game — catch falling treats to feed your pet and beat your high score |
| **Focus timer** | Built-in Pomodoro (customisable work/break lengths) |
| **Break reminders** | Gentle "stand up and stretch" nudges |
| **Sound effects** | Little beeps on feeding, catching, and timer chimes (toggleable) |
| **Start with Windows** | Optional, toggled from Settings (no admin needed) |

Right-click the pet (or the tray icon) for **Feed**, **Play catch game**, and
**How are you?**. Care and the mini-game can be switched off in Settings.

Settings live in `%APPDATA%\DesktopCompanion\settings.json`. The app collects
and transmits **no data**. Run `python desktop_companion.py --selftest` to
render every character to PNGs without opening a window (handy for CI).

The original pets are still here as `desktop_pet.py` (inflatable robot) and
`desktop_pet_classic.py` (running robot) if you prefer them.

---

## What you need first

- **Python 3.10+** installed. During install, tick **"Add Python to PATH"**.
  Check it worked: open Command Prompt and type `python --version`.
- A **Telegram account**.

---

### Easiest way — the setup wizard

```
pip install -r requirements.txt
python monitor_bot.py --setup      # (or: python setup_wizard.py)
```

The wizard walks you through creating a bot with @BotFather, checks your
token actually works, **links the bot to your own Telegram account** (it shows
a one-time code; you send that code to your bot in a private chat and confirm
it's you), writes `config.py` for you, and can set the bot to start with
Windows. Then run `python monitor_bot.py` and send `/help` in Telegram.

The one-time code matters: whoever the bot is linked to can take screenshots
and control the laptop, so the wizard ignores group chats and any message sent
before setup started.

Prefer to do it by hand? The manual steps are below.

### Manual setup

**Step 1 — Create your Telegram bot**

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, pick a name and a username (must end in `bot`).
3. BotFather replies with a **token** like `123456:ABC-DEF...`. Copy it.

**Step 2 — Install the dependencies**

```
pip install -r requirements.txt
```

**Step 3 — Add your token**

Open `config.py` and paste your token into `BOT_TOKEN`. Save. (Or set the
`MONITORBOT_TOKEN` environment variable instead.)

**Step 4 — Find your chat id (one time)**

1. Run the bot:  `python monitor_bot.py`
2. In Telegram, open **your** bot and send `/myid`.
3. It replies with a number. Paste that into `CHAT_ID` in `config.py`. Save.
4. Stop the bot (`Ctrl+C`) and start it again.

That id is what lets the bot send you alerts, and it locks the sensitive
commands to you only.

---

## Using it

Send these to your bot in Telegram:

| Command        | What it does                          |
|----------------|---------------------------------------|
| `/status`      | CPU, RAM, disk, battery               |
| `/battery`     | detailed battery / power state        |
| `/uptime`      | how long the laptop's been on         |
| `/screenshot`  | photo of the current screen           |
| `/photo`       | webcam photo                          |
| `/clipboard`   | read the laptop's clipboard           |
| `/top`         | busiest processes (CPU + memory)      |
| `/disk`        | usage of every drive                  |
| `/net`         | internet status                       |
| `/where`       | Wi-Fi network + approximate location  |
| `/apps`        | what is running, open and closed      |
| `/recent`      | newest files in the watched folder    |
| `/weather [city]` | current weather (no API key)       |
| `/lock`        | lock the screen                       |
| `/sleep`       | put the laptop to sleep               |
| `/notify <msg>`| pop a message box on the laptop       |
| `/speak <msg>` | say something out loud on the laptop  |
| `/mute`        | toggle mute                           |
| `/volup` `/voldown` `[n]` | nudge the volume           |
| `/kill <app>`  | close an app by name (system-protected) |
| `/shutdown`    | shut the laptop down (asks first)     |
| `/abort`       | call off a shutdown                   |
| `/security`    | Defender protection + firewall + BitLocker |
| `/scan` `[quick\|full\|path]` | run a Microsoft Defender antivirus scan |
| `/threats`     | threats Defender has found            |
| `/clean`       | remove active threats                 |
| `/defupdate`   | update virus definitions              |
| `/protect`     | turn real-time protection back on     |
| `/firewall` `[status\|on\|off]` | control Windows Firewall |
| `/ping`        | quick are-you-alive check             |
| `/help`        | command list                          |

The bot also reads `MONITORBOT_TOKEN` and `MONITORBOT_CHAT_ID` from the
environment, so a packaged build can inject credentials without editing
`config.py`. `/kill` refuses critical Windows processes, and every sensitive
command is still locked to your chat id only.

Automatic messages you'll receive:
- **Laptop online** when the bot starts
- **Startup snapshot** - a screenshot and a webcam photo of whoever switched
  the laptop on, sent right after the bot starts. This is an anti-theft
  "who turned my laptop on" snapshot. Turn it off with
  `LOGIN_SNAPSHOT = False` in `config.py`. See the note below.
- **Hourly report** - status, Wi-Fi network and rough location, once an hour.
  Change `STATUS_INTERVAL` in `config.py` (seconds), or set it to `0` to
  switch the report off. The first one arrives `STATUS_FIRST` seconds after
  startup so you can see it works without waiting an hour.
- **App report** - every 5 hours: which apps have a window on screen, which
  are running in the background, and what has opened or closed since the
  last report. Change `APP_REPORT_INTERVAL` in `config.py` (seconds), or set
  it to `0` to switch it off. `/apps` gets one on demand.
- **Internet lost / restored**
- **New file: ...** when a file lands in your Downloads folder
  (change the folder in `config.py` -> `WATCH_FOLDER`)
- **Shutdown started** - if someone shuts the laptop down at the machine
  (see the warning below)

## Antivirus & security (Microsoft Defender)

The bot can act as your **remote antivirus control**, driving **Microsoft
Defender** — the protection engine built into Windows 10/11, which scores at
the **top of independent AV-TEST results**, right alongside K7, McAfee, and
Bitdefender.

The bot does **not** replace or reimplement an antivirus engine — that is a
job for a dedicated product with a signature database and kernel drivers.
Instead it puts a real, world-class engine under your thumb from Telegram:

- `/security` — is real-time protection on, when was the last scan, how old
  are the definitions, plus Firewall, BitLocker, and **pending Windows
  updates**.
- `/firewall [status|on|off]` — check or control the Windows Firewall.
- `/scan quick` — a Defender quick scan (a few minutes).
- `/scan full` — a full-system scan in the background.
- `/scan C:\path\to\file` — scan one file or folder.
- `/threats` — what Defender has detected, and whether it was cleaned,
  quarantined, or removed.
- `/clean` — remove active threats.
- `/defupdate` — update virus definitions.
- `/protect` — turn real-time protection back on if it got switched off.

**Automatic:** every 30 minutes (configurable with `THREAT_CHECK_INTERVAL`)
the bot checks Defender and **alerts you on Telegram** if a threat is detected
or if real-time protection has been turned off.

> **Run as administrator for the full set.** Status and quick scans work
> normally, but full/custom scans, updating definitions, removing threats,
> turning real-time protection on, and reading BitLocker usually need the bot
> to run elevated. Tamper Protection (in Windows Security) can also block the
> bot from changing Defender settings — that's Windows protecting you, and is
> expected.

> **Honesty note for selling it:** describe this as *"control Microsoft
> Defender from Telegram"*, never as *"our own antivirus like K7/McAfee"*.
> The protection is genuinely world-class because it **is** Defender — but
> claiming to be your own AV engine would be inaccurate and would fail store
> review.

## Shutting down from Telegram

Send `/shutdown`. The bot replies with how many apps are open and your
battery level, and two buttons: **Confirm shutdown** and **Cancel**.

Nothing happens until you press Confirm. After that Windows waits
`SHUTDOWN_DELAY` seconds (30 by default) before going down, and `/abort`
calls it off in that window.

The buttons carry their own permission check, so a stranger who somehow
reached your bot cannot press them.

### The shutdown guard, and what it cannot do

If a shutdown or log-off is started **at the laptop**, the bot sends you a
message saying so.

**It cannot stop that shutdown, and it is not an anti-theft lock.** Windows
gives a console program a couple of seconds' notice and then closes it. It
never lets an ordinary program veto a shutdown - even the GUI version of this
(the "an app is preventing shutdown" dialog) has a **Shut down anyway**
button. And nothing at all can help if someone holds the power button or
pulls the battery.

So treat it as *"tell me when it happens"*, not *"ask my permission first"*.
If you want a real lock on the machine, that is BitLocker plus a firmware
password, not a Python script.

### About the location

It is worked out from your **public IP address**, which means it is the point
where your internet provider hands traffic to the internet - not where the
laptop is. On a mobile network it can be out by hundreds of kilometres, and
two lookup services will often name two different cities.

Treat it as *"roughly which city, and has the network changed"*. It is **not**
good enough to find a lost laptop.

Windows can do far better (about 50 m, worked out from nearby Wi-Fi), but only
with Location services switched on - press `Win + R` and run
`ms-settings:privacy-location`. Turning it on also makes Wi-Fi **signal
strength** show up in the report. Set `LOCATION_ENABLED = False` in
`config.py` to leave location out of reports entirely.

## The classic pets (legacy)

These are the original single-character pets. The new **Desktop Companion**
(above) supersedes them with multiple characters, a tray, settings, and the
focus timer — but these still work if you prefer the original robot.

```
python desktop_pet.py
```

A white inflatable robot sits in the top-right corner. He breathes, blinks,
and waves now and then.

- **Left-click** him - he waves back
- **Right-click** him - closes him

To move him to another corner, either pass it on the command line:

```
python desktop_pet.py bottom-right
```

or change `CORNER` at the top of `desktop_pet.py`
(`top-right`, `bottom-right`, `top-left`, `bottom-left`). Size, margin, and
the timing of the blinks and waves are constants in the same block.

**Want your own picture instead?** Drop a PNG named `pet.png` next to
`desktop_pet.py` and it is used in place of the drawn robot - transparency is
kept, and it still breathes and floats. Note that a photo or a downloaded
image cannot blink or wave, since those need artwork that can be redrawn in
different poses; and it will look softer than the drawn robot on a
high-resolution screen, because it can only be stretched, not re-rendered.

The original running robot is still here as `desktop_pet_classic.py` if you
prefer it.

---

## Starting automatically with Windows

This is **already set up**. A shortcut called `Laptop Monitor` lives in your
Startup folder, so both the bot and the desktop pet launch every time you log
in. The bot's console window starts minimised, in the taskbar.

To turn auto-start off: press `Win + R`, type `shell:startup`, press Enter,
and delete `Laptop Monitor` from the folder that opens.

To set it up again on another machine, put a shortcut to `run.bat` in that
same `shell:startup` folder.

### The webcam / photo feature - please read

The startup snapshot and `/photo` take a picture with the built-in camera and
send it to your Telegram. On **your own** laptop, as an anti-theft "who is
using my machine" tool, that is a normal thing to do.

Two things to keep in mind:

- **If other people use this laptop** (family, flatmates, a shared machine),
  photographing them silently is a different matter. Tell them it is running,
  or leave `LOGIN_SNAPSHOT = False`. In some places recording someone without
  their knowledge is against the law - the rules vary by country and state.
- The photo needs the camera to be free. If another app (a call, the Camera
  app) is using it, the shot fails and the bot tells you so rather than
  hanging.

Set `LOGIN_SNAPSHOT = False` to stop the automatic startup photo; `/photo`
still works on demand. `CAMERA_INDEX` picks the camera (0 is the built-in
one).

---

## Anti-theft: alert me when a login fails

This is the part that has to be awake *before* anyone logs in, so it can catch
a thief failing your PIN or password at the lock screen.

**How it is built, and why in two pieces.** Windows keeps programs that start
before login in an isolated background session that cannot see the desktop, so
a bot started that early physically cannot take a screenshot. What it *can* do
is read the security log and send Telegram messages. So the anti-theft alert
is a separate, lightweight script (`antitheft_sentinel.py`) that:

- runs as the SYSTEM account (the only one allowed to read failed-login events),
- is **triggered by the failed-login event itself**, which means it is armed
  from the moment the machine boots - it fires even at the lock screen with
  nobody logged in,
- only *sends* messages, so it never clashes with the main bot (Telegram
  allows one command-poller per bot, but any number of senders).

The interactive bot (screenshots, webcam, `/status`, and the rest) still
starts at login, because before login there is nothing for it to do.

### Status: installed and active

This is already set up on this machine. Failed-logon auditing is on, and a
scheduled task called `LaptopMonitor-FailedLogin` runs as SYSTEM, triggered by
the failed-login event, armed from boot. It was tested against the real log
and confirmed to alert - including telling a wrong PIN apart from a wrong
password.

To set it up again (a fresh Windows install, another machine), open a normal
PowerShell and run this - it pops a UAC prompt and does everything:

```
Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy','Bypass','-File','D:\Mointor\install_antitheft.ps1'
```

The installer switches on failed-logon auditing, registers the SYSTEM task,
and prints any failed logins already in your log so you can see it working.

### Test it

Lock the screen (`Win + L`), type a **wrong** PIN or password once, then log in
properly. Within a few seconds you should get a Telegram alert naming the time
and the account. A webcam photo is attempted too, but Windows usually blocks
the camera at the lock screen, so most often you will get the text alert alone.

### To remove it

```
Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy','Bypass','-File','D:\Mointor\uninstall_antitheft.ps1'
```

### Honest limits

- **On this laptop, a wrong PIN is logged as event 4625** (confirmed - it
  shows up with sub-status 0xc0000380, which is how the alert can say "wrong
  PIN" rather than just "login failed"). On a different machine Windows Hello
  can vary; if a wrong PIN ever stops producing an alert, the installer's
  printout shows what event to point the trigger at instead.
- It reports failures; it cannot *stop* anyone. Someone who never tries to log
  in (just pulls the drive) leaves no failed-login trace. For the machine to
  actually resist theft you want BitLocker plus a firmware/BIOS password - a
  script cannot do that job.

## Packaging & selling it

Everything needed to package Desktop Companion for the **Microsoft Store**
lives in `packaging/`:

```
python packaging/generate_assets.py       # draw icons, tiles, splash, hero
.\packaging\build.ps1 -Version 1.0.0.0     # (Windows) exe -> MSIX
.\packaging\build.ps1 -SelfSign            # build + sign for local testing
```

- [`packaging/SUBMISSION.md`](packaging/SUBMISSION.md) — full, honest
  step-by-step: Partner Center account, identity values, build, upload,
  age rating, privacy policy, and the realistic story for Google Play (which
  would be an Android rewrite).
- [`packaging/store-listing.md`](packaging/store-listing.md) — ready-to-paste
  description and keywords.
- [`packaging/privacy-policy.md`](packaging/privacy-policy.md) — minimal
  privacy policy to host (the app collects no data).

The Monitor Bot is distributed separately as a download (it needs each user's
own Telegram token) — see Part 2 of the submission guide.

## Notes & limits

- The bot only works while the laptop is **on** and the script is **running**.
  Nothing can report from a powered-off machine.
- A clean shutdown/restart just stops the bot; you'll get the "Laptop online"
  message again next time it starts.
- Keep your bot token private — anyone with it can control the bot.
