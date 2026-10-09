@echo off
REM ====================================================================
REM  Desktop Companion - easy installer for Windows
REM
REM  Double-click this file. It installs what the app needs, puts a
REM  "Desktop Companion" shortcut on your desktop, and starts the pet.
REM  No building required - it runs the app straight from the code.
REM ====================================================================
setlocal
title Desktop Companion - Installer
cd /d "%~dp0"

echo ============================================
echo    Desktop Companion - Installer
echo ============================================
echo.

REM --- 1. Is Python installed? ---------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python was not found.
  echo.
  echo     Please install Python 3.10 or newer from:
  echo         https://www.python.org/downloads/
  echo     IMPORTANT: on the first screen, tick "Add Python to PATH".
  echo.
  echo     Then run this installer again.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [OK] Found %%v

REM --- 1b. Is it new enough? (needs 3.10+) --------------------------
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo.
  echo [X] That Python is too old. Desktop Companion needs Python 3.10 or newer.
  echo.
  echo     Please install the latest Python from:
  echo         https://www.python.org/downloads/
  echo     (tick "Add Python to PATH"), then run this installer again.
  echo.
  pause
  exit /b 1
)

REM --- 2. Install the things the app needs ---------------------------
echo.
echo Installing the app's requirements (this can take a minute)...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo [X] Could not install the requirements. See the messages above.
  pause
  exit /b 1
)
echo [OK] Requirements installed.

REM --- 3. Draw the app icon ------------------------------------------
echo.
echo Preparing the app icon...
python "%~dp0packaging\generate_assets.py" >nul 2>&1

REM --- 4. Find pythonw.exe (runs with no console window) -------------
set "PYW="
for /f "delims=" %%p in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%p"
if not defined PYW for /f "delims=" %%p in ('where python.exe 2^>nul') do if not defined PYW set "PYW=%%p"
if not defined PYW set "PYW=pythonw.exe"

REM --- 5. Put a shortcut on the desktop ------------------------------
echo.
echo Creating a desktop shortcut...
set "ICON=%~dp0packaging\assets\app.ico"
set "VBS=%TEMP%\dc_make_shortcut.vbs"
> "%VBS%" echo Set ws = CreateObject("WScript.Shell")
>> "%VBS%" echo sLink = ws.SpecialFolders("Desktop") ^& "\Desktop Companion.lnk"
>> "%VBS%" echo Set lnk = ws.CreateShortcut(sLink)
>> "%VBS%" echo lnk.TargetPath = "%PYW%"
>> "%VBS%" echo lnk.Arguments = """%~dp0desktop_companion.py"""
>> "%VBS%" echo lnk.WorkingDirectory = "%~dp0"
>> "%VBS%" echo If CreateObject("Scripting.FileSystemObject").FileExists("%ICON%") Then lnk.IconLocation = "%ICON%"
>> "%VBS%" echo lnk.Description = "Your friendly desktop pet"
>> "%VBS%" echo lnk.Save
cscript //nologo "%VBS%" >nul 2>&1
del "%VBS%" >nul 2>&1
echo [OK] "Desktop Companion" shortcut added to your desktop.

REM --- 6. Start it now ----------------------------------------------
echo.
echo Starting Desktop Companion...
start "" "%PYW%" "%~dp0desktop_companion.py"

echo.
echo ============================================
echo    All done!
echo.
echo    Your pet is now on screen (top-right corner).
echo    - Right-click it for the menu (Feed, games, settings)
echo    - Drag it anywhere you like
echo    - Start it again any time from the desktop shortcut
echo.
echo    Want the Telegram Monitor Bot too? Run:
echo        python monitor_bot.py --setup
echo ============================================
echo.
pause
endlocal
