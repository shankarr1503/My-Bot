# Laptop Monitor Bot + Desktop Pet

Two things for your Windows laptop:

1. **Monitor bot** — a Telegram bot that reports system health, online/offline
   status, new files, and screenshots on demand.
2. **Desktop pet** — a small robot that runs across the top of your screen.

---

## What you need first

- **Python 3.10+** installed. During install, tick **"Add Python to PATH"**.
  Check it worked: open Command Prompt and type `python --version`.
- A **Telegram account**.

---

## Step 1 — Create your Telegram bot

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, pick a name and a username (must end in `bot`).
3. BotFather replies with a **token** like `123456:ABC-DEF...`. Copy it.

## Step 2 — Install the dependencies

Open Command Prompt in this folder and run:

```
pip install -r requirements.txt
```

## Step 3 — Add your token

Open `config.py` and paste your token into `BOT_TOKEN`. Save.

## Step 4 — Find your chat id (one time)

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
| `/screenshot`  | photo of the current screen           |
| `/photo`       | webcam photo                          |
| `/disk`        | usage of every drive                  |
| `/net`         | internet status                       |
| `/where`       | Wi-Fi network + approximate location  |
| `/apps`        | what is running, open and closed      |
| `/shutdown`    | shut the laptop down (asks first)     |
| `/abort`       | call off a shutdown                   |
| `/help`        | command list                          |

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

## The desktop pet

Run it any time:

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

## Notes & limits

- The bot only works while the laptop is **on** and the script is **running**.
  Nothing can report from a powered-off machine.
- A clean shutdown/restart just stops the bot; you'll get the "Laptop online"
  message again next time it starts.
- Keep your bot token private — anyone with it can control the bot.
