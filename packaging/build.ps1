<#
    build.ps1  -  one-command build for Desktop Companion.

    Produces:
      dist\DesktopCompanion\        the runnable app (folder of files)
      packaging\stage\              MSIX layout (manifest + exe + Images)
      packaging\DesktopCompanion.msix   the installable / submittable package

    Usage (from the repo root, in PowerShell):
      .\packaging\build.ps1                 # build app + MSIX
      .\packaging\build.ps1 -SelfSign       # also make a test cert + sign it
      .\packaging\build.ps1 -SkipMsix       # just the .exe (no packaging)

    Prerequisites:
      * Python 3.10+ with:  pip install -r requirements.txt pyinstaller
      * Windows 10/11 SDK (for makeappx.exe / signtool.exe) when building MSIX.
        Install via Visual Studio, or: winget install Microsoft.WindowsSDK
#>

param(
    [switch]$SelfSign,
    [switch]$SkipMsix,
    [string]$Version = "1.0.0.0"
)

$ErrorActionPreference = "Stop"
$Repo   = Split-Path -Parent $PSScriptRoot
$Pkg    = $PSScriptRoot
$Assets = Join-Path $Pkg "assets"
$Stage  = Join-Path $Pkg "stage"

Write-Host "== Desktop Companion build ==" -ForegroundColor Cyan
Set-Location $Repo

# 1) assets ---------------------------------------------------------------
Write-Host "`n[1/5] Generating image assets..."
python (Join-Path $Pkg "generate_assets.py")

# 2) build the exe --------------------------------------------------------
Write-Host "`n[2/5] Building the executable with PyInstaller..."
pyinstaller --noconfirm --clean (Join-Path $Pkg "DesktopCompanion.spec")

if ($SkipMsix) {
    Write-Host "`nDone. App is in dist\DesktopCompanion\" -ForegroundColor Green
    return
}

# 3) stage the MSIX layout ------------------------------------------------
Write-Host "`n[3/5] Staging MSIX layout..."
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "Images") | Out-Null

Copy-Item (Join-Path $Repo "dist\DesktopCompanion") `
          (Join-Path $Stage "DesktopCompanion") -Recurse

# manifest, with the version stamped in
$manifest = Get-Content (Join-Path $Pkg "AppxManifest.xml") -Raw
$manifest = $manifest -replace 'Version="[0-9.]+"', "Version=`"$Version`""
Set-Content (Join-Path $Stage "AppxManifest.xml") $manifest -Encoding UTF8

foreach ($img in @("StoreLogo.png","Square44x44Logo.png","Square71x71Logo.png",
                   "Square150x150Logo.png","Square310x310Logo.png",
                   "Wide310x150Logo.png","SplashScreen.png")) {
    Copy-Item (Join-Path $Assets $img) (Join-Path $Stage "Images\$img")
}

# 4) make the package -----------------------------------------------------
Write-Host "`n[4/5] Packing MSIX..."
$makeappx = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\makeappx.exe" `
            -ErrorAction SilentlyContinue | Sort-Object FullName | Select-Object -Last 1
if (-not $makeappx) {
    throw "makeappx.exe not found. Install the Windows 10/11 SDK (see the header)."
}
$msix = Join-Path $Pkg "DesktopCompanion.msix"
& $makeappx.FullName pack /d $Stage /p $msix /o
Write-Host "   -> $msix" -ForegroundColor Green

# 5) optional self-sign for local testing --------------------------------
if ($SelfSign) {
    Write-Host "`n[5/5] Creating a self-signed test certificate and signing..."
    $subject = "CN=00000000-0000-0000-0000-000000000000"
    $cert = New-SelfSignedCertificate -Type Custom -Subject $subject `
            -KeyUsage DigitalSignature -FriendlyName "DesktopCompanion Test" `
            -CertStoreLocation "Cert:\CurrentUser\My" `
            -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3",
                             "2.5.29.19={text}")
    $pwd = ConvertTo-SecureString -String "test1234" -Force -AsPlainText
    $pfx = Join-Path $Pkg "DesktopCompanion_Test.pfx"
    Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" `
                          -FilePath $pfx -Password $pwd | Out-Null
    $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" `
                -ErrorAction SilentlyContinue | Sort-Object FullName | Select-Object -Last 1
    & $signtool.FullName sign /fd SHA256 /a /f $pfx /p "test1234" $msix
    Write-Host "`n   Signed. To trust it locally (admin PowerShell):" -ForegroundColor Yellow
    Write-Host "     Import-Certificate -FilePath (your exported .cer) -CertStoreLocation Cert:\LocalMachine\TrustedPeople"
    Write-Host "   Then double-click the .msix to install. For the Store you do NOT sign - Microsoft signs it."
} else {
    Write-Host "`n[5/5] Skipped signing. For the Store, upload the unsigned .msix to Partner Center."
}

Write-Host "`nAll done." -ForegroundColor Green
