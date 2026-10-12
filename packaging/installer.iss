; Inno Setup script for Desktop Companion.
;
; Produces DesktopCompanion-Setup.exe - a normal Windows installer: the user
; downloads one file, double-clicks it, clicks through a wizard, and the app is
; installed with Start-menu and (optional) desktop shortcuts and an uninstaller.
;
; Built automatically by .github/workflows/build-windows.yml after PyInstaller.
; To build by hand on Windows (Inno Setup 6 installed):
;     iscc packaging\installer.iss
;
; Installs per-user (no administrator prompt). The version can be overridden
; from the command line:  iscc /DMyAppVersion=1.2.3 packaging\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Desktop Companion"
#define MyAppExeName "DesktopCompanion.exe"
#define MyAppPublisher "Desktop Companion"

[Setup]
; A stable, unique id for this app (keep it the same across versions).
AppId={{8B7C4E21-2F3A-4D9E-9C1B-7A6D5E4F3C2A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Desktop Companion
DefaultGroupName=Desktop Companion
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; Per-user install: no admin prompt, installs just for the person running it.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=assets\app.ico
Compression=lzma2
SolidCompression=yes
OutputDir=..
OutputBaseFilename=DesktopCompanion-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; The whole PyInstaller output folder (the .exe plus its _internal runtime).
Source: "..\dist\DesktopCompanion\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Desktop Companion"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall Desktop Companion"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Desktop Companion"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the pet as soon as setup finishes.
Filename: "{app}\{#MyAppExeName}"; Description: "Start Desktop Companion now"; Flags: nowait postinstall skipifsilent
