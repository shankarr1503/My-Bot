# Removes everything install_monitor.ps1 set up. Run as Administrator.
$ErrorActionPreference = 'SilentlyContinue'

$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-ExecutionPolicy','Bypass','-NoProfile','-File',"`"$PSCommandPath`"")
    exit
}

$AppDir  = Join-Path $env:ProgramFiles 'MonitorBot'
$DataDir = Join-Path $env:ProgramData 'MonitorBot'

foreach ($t in 'MonitorBot-Agent','MonitorBot-Sentinel','LaptopMonitor-FailedLogin') {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false
    Write-Host "Removed scheduled task: $t"
}

# Stop a running bot, then remove the program files.
Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
    Where-Object { $_.CommandLine -like "*MonitorBot*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Remove-Item -Recurse -Force $AppDir
Write-Host "Removed $AppDir"

if ($args -contains '-KeepConfig') {
    Write-Host "Kept $DataDir (config and logs) as requested."
} else {
    Remove-Item -Recurse -Force $DataDir
    Write-Host "Removed $DataDir (config and logs)."
}

Write-Host "`nDone. (Failed-logon auditing was left enabled; to turn it off:"
Write-Host "  auditpol /set /subcategory:\"Logon\" /failure:disable )"
