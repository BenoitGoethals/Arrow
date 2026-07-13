; Inno Setup script — Arrow Front Windows installer.
; Build (after PyInstaller has produced dist\ArrowFront\):
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" front\packaging\arrow-front.iss
; or just run front\packaging\build_windows.ps1 which does both steps.
;
; Requires Inno Setup 6:  https://jrsoftware.org/isdl.php

#define AppName "Arrow Front"
#define AppVersion "1.0.0"
#define AppPublisher "Arrow"
#define AppExeName "ArrowFront.exe"

[Setup]
; AppId uniquely identifies the app for upgrades/uninstall — never change it.
AppId={{8109EF63-346D-41E7-B325-87C6B2586DFE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Arrow Front
DefaultGroupName=Arrow Front
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir={#SourcePath}\..\..\dist\installer
OutputBaseFilename=ArrowFront-Setup-{#AppVersion}
SetupIconFile={#SourcePath}\..\resources\arrow_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 64-bit only (Qt/WebEngine is x64).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-machine install (Program Files) needs admin; use "lowest" + {autopf}=
; {localappdata} for a per-user install with no UAC prompt.
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire PyInstaller onedir bundle. recursesubdirs pulls in Qt, WebEngine,
; the map assets and the default MBTiles. ignoreversion so our files always win.
Source: "{#SourcePath}\..\..\dist\ArrowFront\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Arrow Front"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Arrow Front"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Arrow Front"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,Arrow Front}"; Flags: nowait postinstall skipifsilent
