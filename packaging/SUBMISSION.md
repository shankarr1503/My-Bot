# Shipping the suite — Microsoft Store & Google Play

This guide takes **Desktop Companion** from source to a published Microsoft
Store listing, and explains honestly what it would take to reach Google Play.

> **The short version**
> - **Desktop Companion → Microsoft Store:** realistic and ready. The app is a
>   packaged Win32 (MSIX) app. Everything you need is in `packaging/`.
> - **Monitor Bot → any store:** not suitable as a consumer store app (each
>   user must create their own Telegram bot token). Ship it as a downloadable
>   installer/zip to power users instead — see the last section.
> - **Google Play (Android):** none of this code runs on Android. It would be a
>   from-scratch rewrite. The plan is at the end.

---

## Part 1 — Desktop Companion on the Microsoft Store

### What you'll need
1. A **Microsoft Partner Center** developer account.
   One-time registration fee (about **$19** for an individual, ~$99 for a
   company). Sign up at <https://partner.microsoft.com/dashboard>.
2. **Python 3.10+** with the build tools:
   ```
   pip install -r requirements.txt pyinstaller
   ```
3. The **Windows 10/11 SDK** (provides `makeappx.exe` and `signtool.exe`):
   ```
   winget install Microsoft.WindowsSDK.10.0.22621
   ```

### Step 1 — Reserve the app name
In Partner Center: **Apps and games → New product → MSIX or PWA app**, then
reserve a name (e.g. *Desktop Companion*, or a unique variant if taken).

### Step 2 — Get your identity values
Open the reserved product → **Product management → Product identity**. Copy:
- **Package/Identity/Name** (e.g. `12345Publisher.DesktopCompanion`)
- **Publisher** (e.g. `CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)
- **Publisher display name**

Paste these three into `packaging/AppxManifest.xml`, replacing the
placeholders (`Identity Name`, `Identity Publisher`, `PublisherDisplayName`).

### Step 3 — Build the package
From the repo root, in PowerShell:
```
.\packaging\build.ps1 -Version 1.0.0.0
```
This generates the icons, builds `DesktopCompanion.exe` with PyInstaller,
stages the MSIX layout, and produces **`packaging\DesktopCompanion.msix`**.

> **Do not sign the package for the Store.** Microsoft re-signs it with your
> Partner Center identity on upload. Signing is only for *local* testing — see
> "Test locally" below.

### Step 4 — Upload and fill in the listing
In your reserved product → **Start a submission**:

- **Packages:** upload `DesktopCompanion.msix`.
- **Pricing and availability:** Free, or set a price / free trial.
- **Age ratings:** complete the questionnaire. The app has no ads, no user
  content, no data collection → it rates **E / 3+** everywhere.
- **Store listing:**
  - *Description:* see `packaging/store-listing.md` for ready-to-paste copy.
  - *Screenshots:* use `packaging/assets/hero.png` (1280×720) and add 2–3
    real screenshots of the pet + settings window on your desktop. The Store
    requires at least one 1366×768 or 1920×1080 screenshot.
  - *Store logo:* `packaging/assets/Square150x150Logo.png` or `StoreLogo.png`.
- **Privacy policy URL:** required by the Store. Because Desktop Companion
  **collects and transmits no data** (settings stay in a local JSON file), a
  one-paragraph page saying exactly that is enough. A template is in
  `packaging/privacy-policy.md` — host it anywhere public (GitHub Pages works).

### Step 5 — Submit
Click **Submit to the Store**. Certification typically takes a few hours to a
couple of days. If it's rejected, Partner Center tells you exactly why; the
usual first-timer issues are a mismatched identity (Step 2) or a missing
privacy policy (Step 4).

### Test locally before you submit (optional but wise)
```
.\packaging\build.ps1 -SelfSign
```
This makes a self-signed test certificate and signs the MSIX. Trust the cert
once (admin PowerShell), then double-click the `.msix` to install it exactly
as a user would. Remove the test cert and the app afterwards.

### Why `runFullTrust`?
Desktop Companion is a packaged desktop (Win32) app, so it declares the
`runFullTrust` capability in the manifest. The Store shows a "uses all system
resources" notice for this — that's standard for every packaged desktop app
(including ones from Adobe, Spotify, etc.) and is not a blocker.

---

## Part 2 — The Monitor Bot (power-user distribution)

The bot is deliberately **not** a store app: it only works once the user
creates their *own* Telegram bot with @BotFather and pastes in a token, which
no consumer-store reviewer or buyer will do. Distribute it as a download:

```
pyinstaller packaging/MonitorBot.spec
```
Zip `dist\MonitorBot\` with the `README.md`. Users unzip and run
`MonitorBot.exe --setup` once: the wizard checks their token, links their own
Telegram account with a one-time code, and writes `config.py` beside the
`.exe`. After that, plain `MonitorBot.exe` starts the bot. (Alternatively they
can set the `MONITORBOT_TOKEN` / `MONITORBOT_CHAT_ID` environment variables.)
Host the zip on GitHub Releases, itch.io, or your own site.

> The build bundles only the blank `config.example.py` template - never your
> own `config.py` - so your bot token can't leak inside the `.exe` you ship.

If you later want it on the Store too, the path is to add a first-run setup
wizard that walks the user through creating a bot — but that's a product
decision, not a packaging one.

---

## Part 3 — Google Play (Android): the honest plan

**None of this code runs on Android.** Python + tkinter + Windows APIs have no
Android runtime. Reaching Google Play means a rewrite. Two realistic routes:

1. **Flutter / Kotlin native app.** Rebuild the companion as an Android live
   wallpaper or floating-overlay widget (`TYPE_APPLICATION_OVERLAY`), with the
   focus timer and break reminders as the core value. Reuse only the *design*
   (characters, messages, timer logic) — all of which is documented in
   `desktop_companion.py` and portable.
2. **Keep the mascots, rethink the app.** The characters and the
   focus-timer/break-reminder idea are the sellable part. On mobile that most
   naturally becomes a **focus-timer app with a pet that reacts** — a proven
   Play Store category (cf. Forest). That's a product worth scoping on its own.

Requirements either way: a **Google Play Developer account** (one-time $25),
an Android build (`.aab`), a privacy policy, and the Data Safety form. The
Windows work here doesn't block any of it — but it also doesn't shortcut it.

---

## File map for packaging

| File | Purpose |
|------|---------|
| `packaging/generate_assets.py` | draws every icon/tile/splash from the mascot art |
| `packaging/DesktopCompanion.spec` | PyInstaller build for the pet (windowed) |
| `packaging/MonitorBot.spec` | PyInstaller build for the bot (console) |
| `packaging/AppxManifest.xml` | MSIX manifest (edit the 3 identity values) |
| `packaging/build.ps1` | one-command: assets → exe → MSIX (+ optional sign) |
| `packaging/store-listing.md` | ready-to-paste Store description & keywords |
| `packaging/privacy-policy.md` | minimal privacy policy to host |
