<#
.SYNOPSIS
    Code-sign one or more Windows files (.exe / installer) with Authenticode.

.DESCRIPTION
    Provider-neutral signing helper for the build workflow. It uses the
    Windows SDK's signtool.exe with a PFX certificate supplied through
    environment variables, so it needs no vendor-specific GitHub Action and
    turns on the moment the secrets exist.

    It is called from .github/workflows/build-windows.yml, but only when the
    repository variable SIGN_BINARIES is set to "true". When that variable is
    unset the signing steps are skipped entirely and the build is unsigned,
    exactly as before.

    Environment variables (set these as GitHub repository secrets):
      SIGNING_PFX_BASE64     (required) the code-signing certificate, a .pfx
                             file encoded as base64. See packaging/CODE-SIGNING.md.
      SIGNING_PFX_PASSWORD   (optional) the password protecting the .pfx.
      SIGNING_TIMESTAMP_URL  (optional) RFC-3161 timestamp server. Defaults to
                             http://timestamp.digicert.com. Timestamping lets
                             the signature stay valid after the cert expires.

    NOTE: This PFX path works for any certificate you can export as a .pfx
    file. Modern EV certificates and many new OV certificates are bound to a
    hardware token or cloud HSM and cannot be exported — for those, use the
    vendor's own signing step instead (see CODE-SIGNING.md, "Using a cloud-HSM
    or Azure certificate"). This script deliberately fails loudly rather than
    producing an unsigned build when it is asked to sign but cannot.

.PARAMETER Files
    One or more paths to sign. Missing files are an error.

.EXAMPLE
    pwsh packaging/sign-windows.ps1 dist/App/App.exe MyApp-Setup.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]] $Files
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$pfxBase64    = $env:SIGNING_PFX_BASE64
$pfxPassword  = $env:SIGNING_PFX_PASSWORD
$timestampUrl = if ([string]::IsNullOrWhiteSpace($env:SIGNING_TIMESTAMP_URL)) {
    "http://timestamp.digicert.com"
} else {
    $env:SIGNING_TIMESTAMP_URL
}

if ([string]::IsNullOrWhiteSpace($pfxBase64)) {
    throw "SIGNING_PFX_BASE64 is not set. Signing is enabled (SIGN_BINARIES=true) " +
          "but no certificate was provided. Add the SIGNING_PFX_BASE64 secret, or " +
          "set SIGN_BINARIES back to false to build unsigned. See packaging/CODE-SIGNING.md."
}

# --- Locate signtool.exe from the Windows SDK (present on windows-latest) ----
function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        $candidate = Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    throw "signtool.exe not found. Install the Windows SDK, or run on a GitHub windows-latest runner where it is preinstalled."
}

$signtool = Find-SignTool
Write-Host "Using signtool: $signtool"

# --- Materialise the PFX into a temp file, sign, then shred it ---------------
$pfxPath = Join-Path ([System.IO.Path]::GetTempPath()) ("codesign-" + [guid]::NewGuid().ToString("N") + ".pfx")
try {
    try {
        $bytes = [System.Convert]::FromBase64String($pfxBase64.Trim())
    } catch {
        throw "SIGNING_PFX_BASE64 is not valid base64. Re-encode the .pfx (see CODE-SIGNING.md)."
    }
    [System.IO.File]::WriteAllBytes($pfxPath, $bytes)

    foreach ($file in $Files) {
        if (-not (Test-Path -LiteralPath $file)) {
            throw "Cannot sign '$file': file not found."
        }
        Write-Host "Signing $file ..."

        $signArgs = @(
            "sign",
            "/fd", "SHA256",
            "/tr", $timestampUrl,
            "/td", "SHA256",
            "/f",  $pfxPath
        )
        if (-not [string]::IsNullOrEmpty($pfxPassword)) {
            $signArgs += @("/p", $pfxPassword)
        }
        $signArgs += $file

        & $signtool @signArgs
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed to sign '$file' (exit $LASTEXITCODE)."
        }

        & $signtool "verify" "/pa" $file
        if ($LASTEXITCODE -ne 0) {
            throw "Signature verification failed for '$file' (exit $LASTEXITCODE)."
        }
        Write-Host "Signed and verified: $file"
    }
}
finally {
    if (Test-Path -LiteralPath $pfxPath) {
        Remove-Item -LiteralPath $pfxPath -Force -ErrorAction SilentlyContinue
    }
}
