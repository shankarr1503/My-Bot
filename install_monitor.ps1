# ============================================================================
#  Monitor Bot - installer (run as Administrator)
#
#  Sets the whole thing up so it is production-ready and hands-off:
#
#    1. Copies the app to %ProgramFiles%\MonitorBot  (only Administrators can
#       write there, so no one can plant code the elevated bot would import --
#       this is the fix for the privilege-escalation the old D:\Mointor setup
#       had).
#    2. Creates %ProgramData%\MonitorBot for config.py / state / logs, locked
#       down to SYSTEM + Administrators (read-only for normal users), so the
#       config the elevated bot imports can't be tampered with.
#    3. Registers TWO scheduled tasks:
#         * MonitorBot-Agent    - starts the bot AT LOG ON, elevated (highest
#                                 privileges, no UAC prompt), in your session so
#                                 it can screenshot/webcam. This is the
#                                 "runs as admin, starts automatically" part.
#         * MonitorBot-Sentinel - event-triggered on a failed logon (4625/4776),
#                                 runs as SYSTEM, armed from boot, so it catches
#                                 a thief at the lock screen before anyone logs in.
#    4. Turns on failed-logon auditing.
#
#  Nothing here is machine-specific: paths and the Python/exe to run are all
#  discovered. Run from an elevated PowerShell, or just right-click > Run with
#  PowerShell and accept the UAC prompt.
# ============================================================================

$ErrorActionPreference = 'Stop'

# --- self-elevate if we're not already admin ---
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Asking for administrator rights..." -ForegroundColor Cyan
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-ExecutionPolicy','Bypass','-NoProfile','-File',"`"$PSCommandPath`"")
    exit
}

$Source   = $PSScriptRoot
$AppDir   = Join-Path $env:ProgramFiles 'MonitorBot'
$DataDir  = Join-Path $env:ProgramData 'MonitorBot'
$BotTask  = 'MonitorBot-Agent'
$SenTask  = 'MonitorBot-Sentinel'

Write-Host "`nMonitor Bot installer" -ForegroundColor Green
Write-Host "  app  -> $AppDir"
Write-Host "  data -> $DataDir`n"

# --- 1. find the Python to run (prefer pythonw so there's no console window) ---
function Find-Python {
    foreach ($name in 'pythonw.exe','python.exe') {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python","$env:ProgramFiles\Python*","C:\Python*")) {
        $hit = Get-ChildItem -Path $base -Filter 'pythonw.exe' -Recurse -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}
$Pyw = Find-Python
if (-not $Pyw) {
    throw "Python not found. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add Python to PATH'), then re-run."
}
Write-Host "[1/6] Using Python: $Pyw" -ForegroundColor Cyan

# --- 2. copy the app into Program Files (admin-only, so code can't be planted) ---
Write-Host "[2/6] Copying app files to $AppDir ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
$files = @(
    'monitor_bot.py','antitheft_sentinel.py','suite_common.py','setup_wizard.py',
    'bot_dashboard.py','monitor_app.py','config.example.py',
    'requirements.txt'
)
foreach ($f in $files) {
    $src = Join-Path $Source $f
    if (Test-Path $src) { Copy-Item $src -Destination $AppDir -Force }
}

# --- 3. data dir: create it, migrate an existing config, lock it down ---
Write-Host "[3/6] Preparing data folder $DataDir ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$cfgDst = Join-Path $DataDir 'config.py'
if (-not (Test-Path $cfgDst)) {
    $cfgSrc = Join-Path $Source 'config.py'
    if (Test-Path $cfgSrc) {
        Copy-Item $cfgSrc -Destination $cfgDst -Force
        Write-Host "      migrated your existing config.py"
    } else {
        Copy-Item (Join-Path $Source 'config.example.py') -Destination $cfgDst -Force
        Write-Host "      wrote a blank config.py (set your token via the Dashboard)"
    }
}
Copy-Item (Join-Path $Source 'config.example.py') -Destination $DataDir -Force

# Lock the data dir: SYSTEM + Administrators full control; normal users read &
# execute only. This stops a medium-integrity (normal-user) process from editing
# config.py -- which the elevated bot and the SYSTEM sentinel both import -- so a
# wrong-PIN-then-code-execution escalation is no longer possible.
& icacls $DataDir /inheritance:r | Out-Null
& icacls $DataDir /grant:r "*S-1-5-18:(OI)(CI)F"    | Out-Null  # SYSTEM
& icacls $DataDir /grant:r "*S-1-5-32-544:(OI)(CI)F"| Out-Null  # Administrators
& icacls $DataDir /grant:r "*S-1-5-32-545:(OI)(CI)RX"| Out-Null # Users: read/exec

# --- 4. the bot: start at log on, elevated, in the user's session ---
Write-Host "[4/6] Registering '$BotTask' (starts at log on, as admin) ..." -ForegroundColor Cyan
$botScript = Join-Path $AppDir 'monitor_bot.py'
$botAction = New-ScheduledTaskAction -Execute $Pyw `
    -Argument "`"$botScript`"" -WorkingDirectory $AppDir
$botTrigger = New-ScheduledTaskTrigger -AtLogOn
# Run as the user who is installing, with highest privileges -> elevated without
# a UAC prompt on every boot, and inside the interactive session so screenshots
# and the webcam work.
$botPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest
$botSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Unregister-ScheduledTask -TaskName $BotTask -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $BotTask -Action $botAction -Trigger $botTrigger `
    -Principal $botPrincipal -Settings $botSettings `
    -Description 'Monitor Bot - starts at log on, elevated' | Out-Null

# --- 5. the sentinel: event-triggered, SYSTEM, armed from boot ---
Write-Host "[5/6] Registering '$SenTask' (failed-logon alert, as SYSTEM) ..." -ForegroundColor Cyan
& auditpol /set /subcategory:"Logon" /failure:enable | Out-Null

$subscription = @'
<QueryList><Query Id="0" Path="Security"><Select Path="Security">*[System[(EventID=4625 or EventID=4776)]]</Select></Query></QueryList>
'@
$class = Get-CimClass MSFT_TaskEventTrigger root/Microsoft/Windows/TaskScheduler
$senTrigger = New-CimInstance -CimClass $class -ClientOnly
$senTrigger.Enabled = $true
$senTrigger.Subscription = $subscription

$senScript = Join-Path $AppDir 'antitheft_sentinel.py'
$senAction = New-ScheduledTaskAction -Execute $Pyw `
    -Argument "`"$senScript`" once" -WorkingDirectory $AppDir
$senPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
    -LogonType ServiceAccount -RunLevel Highest
$senSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances Queue -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Unregister-ScheduledTask -TaskName $SenTask -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $SenTask -Trigger $senTrigger -Action $senAction `
    -Principal $senPrincipal -Settings $senSettings `
    -Description 'Monitor Bot - anti-theft failed-logon alert (SYSTEM, from boot)' | Out-Null

# --- 6. install Python dependencies for all users ---
Write-Host "[6/6] Installing Python requirements ..." -ForegroundColor Cyan
$py = $Pyw -replace 'pythonw\.exe$','python.exe'
if (-not (Test-Path $py)) { $py = $Pyw }
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r (Join-Path $AppDir 'requirements.txt')

Write-Host "`nDone." -ForegroundColor Green
Write-Host "Set your Telegram token: run the Dashboard (as administrator) and use the Connect tab,"
Write-Host "or edit $cfgDst directly. The bot starts automatically at your next log on;"
Write-Host "to start it now without rebooting, run:  Start-ScheduledTask -TaskName '$BotTask'"
Write-Host "`nTEST the anti-theft alert: lock the screen (Win+L), type a WRONG PIN once, then log in."
