; Inno Setup script for the Monitor Bot Dashboard.
;
; Produces MonitorBotDashboard-Setup.exe - a normal Windows installer for the
; bot's control-panel app (which also runs the bot itself). Installs per-user,
; no administrator prompt.
;
; Built automatically by .github/workflows/build-windows.yml after PyInstaller.
; By hand on Windows (Inno Setup 6):  iscc packaging\installer_dashboard.iss
; Version override:  iscc /DMyAppVersion=1.2.3 packaging\installer_dashboard.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Monitor Bot Dashboard"
#define MyAppExeName "MonitorBotDashboard.exe"
#define MyAppPublisher "Monitor Bot"

[Setup]
AppId={{3F2A9C64-7B51-4E8D-9A2C-1D6E5F4B3A7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Monitor Bot Dashboard
DefaultGroupName=Monitor Bot Dashboard
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=assets\app.ico
Compression=lzma2
SolidCompression=yes
OutputDir=..
OutputBaseFilename=MonitorBotDashboard-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\MonitorBotDashboard\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Monitor Bot Dashboard"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall Monitor Bot Dashboard"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Monitor Bot Dashboard"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Open the Dashboard now"; Flags: nowait postinstall skipifsilent
