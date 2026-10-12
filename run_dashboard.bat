@echo off
REM Double-click to open the Monitor Bot Dashboard.
REM Prefer pythonw.exe (no console window); fall back to python.exe.
cd /d "%~dp0"
set "PYW=pythonw.exe"
where pythonw.exe >nul 2>&1 || set "PYW=python.exe"
start "" "%PYW%" "%~dp0bot_dashboard.py"
