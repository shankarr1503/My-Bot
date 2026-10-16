# Code signing — removing the Windows "unknown publisher" warning

When someone downloads `MonitorBotDashboard-Setup.exe` or
`DesktopCompanion-Setup.exe` today, Windows SmartScreen shows a blue
"Windows protected your PC — unknown publisher" box, and Chrome may say the
file "isn't commonly downloaded." Nothing is wrong with the files — Windows
just trusts a program more when it carries a **digital signature** from a
publisher a Certificate Authority (CA) has verified.

This guide explains how to get a code-signing certificate and switch signing
on. **The build is already wired for it** — see
[Turning signing on](#turning-signing-on). Until you do, builds stay unsigned
and keep working exactly as now.

---

## The three things to know first

1. **There is no free way to remove the warning.** Self-signed certificates
   do not count: Windows only trusts certificates that chain up to a CA it
   already recognizes. Every real option below costs money.

2. **Since June 2023, the private key can't just be a file.** CAs must now
   issue code-signing certificates onto a hardware token (a USB device) or a
   cloud HSM (a key-storage service). That's why old "put your `.pfx` in a
   secret" tutorials no longer apply to brand-new OV/EV certificates — the key
   can't be exported. The cloud options below exist precisely so this still
   works in automated builds.

3. **Two different outcomes:**
   - **Instant trust** — an **EV** certificate, or **Azure Artifact Signing**,
     removes the SmartScreen warning from the very first download.
   - **Reputation over time** — a standard **OV** certificate signs the file,
     but the warning only fades gradually as Microsoft sees more people
     download your signed app and builds "reputation" for your publisher
     identity. Can take days to weeks and a number of downloads.

---

## Pick a route

| Route | Cost | Removes warning | Eligibility | CI fit |
|---|---|---|---|---|
| **Azure Artifact Signing** (was "Trusted Signing") | ~**$9.99/mo** | Fast (builds reputation quickly; no token) | Orgs in US/CA/EU/UK; **individuals in US & Canada only** | Excellent — official GitHub Action |
| **EV certificate** (SSL.com, DigiCert, …) | ~**$300–600/yr** | **Instant** | Strict identity vetting (business or validated individual) | Good — via the CA's cloud-HSM signer |
| **OV / Individual certificate** | ~**$200–400/yr** | Gradual (reputation) | Lighter vetting | Good — cloud HSM, or legacy `.pfx` |
| **Legacy `.pfx` file** | varies | Gradual | Only older/renewable or internal certs (new ones are HSM-bound) | **This is what the build wires by default** |

**Recommendation for this project (a solo/indie app):**
If you're in the **US or Canada**, go **Azure Artifact Signing** — it's by far
the cheapest, needs no USB token, and plugs straight into GitHub Actions.
If you need the warning gone **instantly** (e.g. you're about to share widely),
or you're outside Azure's eligible countries, buy an **EV certificate** from
SSL.com or DigiCert and sign through their cloud HSM.

---

## How the build is wired

The workflow (`.github/workflows/build-windows.yml`) has two signing steps that
are **skipped unless** the repository variable `SIGN_BINARIES` is `true`:

1. **Sign the app executables** — runs after PyInstaller, before the installers
   are built, so the installed app is signed.
2. **Sign the installers** — runs after Inno Setup, so the downloaded
   `*-Setup.exe` files are signed (this is the signature SmartScreen checks).

Both call `packaging/sign-windows.ps1`, which uses the Windows SDK's
`signtool.exe` with a **PFX certificate** read from secrets. This is the one
method that needs no vendor-specific tooling, so it "just turns on" when the
secrets are present. It works with any certificate you can export as a `.pfx`.

> **If your certificate is HSM-bound** (most new EV and OV certs, and Azure),
> it can't be exported to a `.pfx`. Use the vendor's signer instead — see
> [Using a cloud-HSM or Azure certificate](#using-a-cloud-hsm-or-azure-certificate).
> It's a one-step swap.

---

## Turning signing on

### Step 1 — set the on/off switch
In the GitHub repo: **Settings → Secrets and variables → Actions → Variables**
tab → **New repository variable**:

- Name: `SIGN_BINARIES`  ·  Value: `true`

(Set it back to `false`, or delete it, to build unsigned again.)

### Step 2 — add the certificate

**If you have a `.pfx` file** (the wired-in path), add these as repository
**Secrets** (the *Secrets* tab, not Variables):

| Secret | Value |
|---|---|
| `SIGNING_PFX_BASE64` | your `.pfx` file, base64-encoded (below) |
| `SIGNING_PFX_PASSWORD` | the password on the `.pfx` (omit if none) |

Optionally add a **Variable** `SIGNING_TIMESTAMP_URL` to override the default
timestamp server (`http://timestamp.digicert.com`).

Encode the `.pfx` to base64:

```powershell
# Windows PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("mycert.pfx")) | Set-Content cert.b64
```
```bash
# macOS / Linux
base64 -w0 mycert.pfx > cert.b64     # on macOS: base64 -i mycert.pfx -o cert.b64
```
Paste the contents of `cert.b64` as the `SIGNING_PFX_BASE64` secret.

**If your certificate is HSM-bound / Azure**, skip the secrets above and follow
[the next section](#using-a-cloud-hsm-or-azure-certificate) instead.

### Step 3 — build
Push to `main`, or run the workflow with a `release_tag` (e.g. `v1.2.0`). The
signing steps now run, and the Release notes automatically switch to the
"digitally signed" wording.

---

## Route-by-route setup

### Azure Artifact Signing (recommended, cheapest)

1. In the **Azure portal**, create a **Trusted Signing / Artifact Signing**
   account (choose a region, e.g. East US), then a **Certificate Profile**
   (type **Public Trust**).
2. Complete **identity validation** (individual: government photo ID + a selfie
   via Microsoft Entra Verified ID; usually approved within a day). This can
   only be done in the portal.
3. Create an **App Registration** (service principal) and grant it the
   **Code Signing Certificate Profile Signer** role on the signing account.
   Note its **tenant ID, client ID, client secret**.
4. Replace the **two `Sign …` steps** in the workflow with the vendor action.
   Add your account/profile/region as repo variables and the three credentials
   as secrets, then set `SIGN_BINARIES=true`:

```yaml
      - name: Sign the app executables
        if: vars.SIGN_BINARIES == 'true'
        uses: azure/trusted-signing-action@v0   # verify latest; now also azure/artifact-signing-action@v2
        with:
          azure-tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          azure-client-id: ${{ secrets.AZURE_CLIENT_ID }}
          azure-client-secret: ${{ secrets.AZURE_CLIENT_SECRET }}
          endpoint: ${{ vars.AZURE_SIGNING_ENDPOINT }}                 # e.g. https://eus.codesigning.azure.net/
          trusted-signing-account-name: ${{ vars.AZURE_SIGNING_ACCOUNT }}
          certificate-profile-name: ${{ vars.AZURE_SIGNING_PROFILE }}
          files-folder: ${{ github.workspace }}\dist
          files-folder-filter: exe
          files-folder-recurse: true
          file-digest: SHA256
          timestamp-rfc3161: http://timestamp.acs.microsoft.com
          timestamp-digest: SHA256
```
   Add a second copy for the installers with
   `files-folder: ${{ github.workspace }}` and `files-folder-recurse: false`.

> The action and its inputs are evolving (the product was renamed from
> "Trusted Signing" to "Artifact Signing"; the newer action uses
> `signing-account-name`). **Check the action's current README** before
> copying — https://github.com/Azure/trusted-signing-action and
> https://github.com/Azure/artifact-signing-action.

### EV certificate — instant trust (SSL.com eSigner shown)

1. Buy an **EV Code Signing** certificate (SSL.com, DigiCert, Sectigo, …) and
   complete the business/identity validation. The key lives in the CA's cloud
   HSM (no USB token needed for CI).
2. For **SSL.com eSigner**, add their GitHub Action in place of the two
   `Sign …` steps, with your eSigner credentials + TOTP secret as repo secrets:

```yaml
      - name: Sign the app executables
        if: vars.SIGN_BINARIES == 'true'
        uses: sslcom/esigner-codesign@develop   # verify latest tag in their README
        with:
          command: sign
          username: ${{ secrets.ESIGNER_USERNAME }}
          password: ${{ secrets.ESIGNER_PASSWORD }}
          credential_id: ${{ secrets.ESIGNER_CREDENTIAL_ID }}
          totp_secret: ${{ secrets.ESIGNER_TOTP_SECRET }}
          file_path: ${{ github.workspace }}/dist/MonitorBotDashboard/MonitorBotDashboard.exe
          override: true
          malware_block: false
          environment_name: PROD
```
   Repeat per file (eSigner signs one file per step). DigiCert's equivalent is
   **KeyLocker** with their `ssm-code-signing` tooling driving `signtool`.

### Legacy `.pfx` (the wired-in default)

Already covered under [Turning signing on](#turning-signing-on) — add
`SIGNING_PFX_BASE64` (+ password) and set `SIGN_BINARIES=true`. No workflow
edit needed. Only works if your CA still issues an exportable `.pfx` (older
OV certs, renewals, or an internal/enterprise CA for in-house distribution).

---

## Verifying a signed build

Download a `*-Setup.exe` from the Release and check it on Windows:

```powershell
Get-AuthenticodeSignature .\MonitorBotDashboard-Setup.exe | Format-List
# Status should be "Valid"; SignerCertificate shows your publisher name.
```
Or right-click the file → **Properties → Digital Signatures** tab.

---

## A note on reputation

Even with a valid signature, a brand-new **OV** publisher identity can still
trip SmartScreen for a while until it has "reputation." Each new certificate
starts fresh. **EV** certificates and **Azure Artifact Signing** are trusted
immediately (EV) or build reputation quickly, which is why they're the
recommended routes if you want the warning gone now. Keep the same certificate
across releases — switching certs resets reputation.

---

## Sources

- Azure Trusted Signing quickstart & pricing:
  https://learn.microsoft.com/azure/trusted-signing/quickstart
- Azure action(s):
  https://github.com/Azure/trusted-signing-action ·
  https://github.com/Azure/artifact-signing-action
- SSL.com eSigner CI signing:
  https://www.ssl.com/guide/remote-ev-code-signing-with-esigner/
- DigiCert KeyLocker: https://docs.digicert.com/en/digicert-keylocker.html
- Microsoft on SmartScreen & reputation:
  https://learn.microsoft.com/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/
