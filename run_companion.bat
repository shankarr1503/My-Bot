@echo off
REM Double-click to start Desktop Companion.
REM Prefer pythonw.exe (no console window); fall back to python.exe.
cd /d "%~dp0"
set "PYW=pythonw.exe"
where pythonw.exe >nul 2>&1 || set "PYW=python.exe"
start "" "%PYW%" "%~dp0desktop_companion.py"
