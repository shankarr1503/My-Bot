@echo off
REM Double-click to start Desktop Companion (no console window stays open).
cd /d "%~dp0"
start "" pythonw.exe "%~dp0desktop_companion.py"
