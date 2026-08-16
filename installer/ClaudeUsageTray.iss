; Inno Setup script for Claude Usage Tray.
; Builds a per-user (no-admin) installer that bundles the app together with
; Python's official *embeddable* runtime. There is no PyInstaller/Nuitka packed
; executable anywhere in here, so antivirus ML heuristics (Wacatac & friends)
; have nothing to flag. Shortcuts launch the app via the bundled pythonw.exe.
;
; The payload under .\payload is produced by build-installer.ps1.

#define AppName "Claude Usage Tray"
#define AppVersion "1.2.1"
#define AppPublisher "zoutmax"
#define AppURL "https://github.com/ZoutMax/Claude-Usage-Tray-Windows"
#define AppExe "python\pythonw.exe"
#define AppScript "claude_usage_tray.py"

[Setup]
AppId={{B9E5B0A1-4C7D-4E2A-9F3B-7A1C2D3E4F50}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist-installer
OutputBaseFilename=ClaudeUsageTray-Setup-{#AppVersion}
SetupIconFile=payload\assets\app.ico
UninstallDisplayIcon={app}\assets\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

[Files]
Source: "payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Tasks]
Name: "startup"; Description: "Start {#AppName} automatically when I sign in"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: """{app}\{#AppScript}"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: """{app}\{#AppScript}"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Tasks: startup
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: """{app}\{#AppScript}"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Parameters: """{app}\{#AppScript}"""; WorkingDir: "{app}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
; The saved token and alert settings. Leaving a credential on disk after an
; uninstall is worse than making the user sign in again if they reinstall.
Type: filesandordirs; Name: "{userappdata}\ClaudeUsageTray"

[Code]
// The tray runs FROM the install directory (python\pythonw.exe), so while it is
// running Windows locks those files and they cannot be deleted. The uninstaller
// still reports success, leaving ~27 MB of Python behind -- and an upgrade
// installs over a locked runtime. So stop our own tray first, in both cases.
//
// Matched on the executable path under {app}, not on the image name: killing
// every pythonw.exe would take down unrelated Python apps the user is running.
procedure StopTray();
var
  ResultCode: Integer;
  Cmd: String;
begin
  Cmd := '-NoProfile -WindowStyle Hidden -Command "' +
         'Get-Process pythonw,python -ErrorAction SilentlyContinue | ' +
         'Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | ' +
         'Stop-Process -Force -ErrorAction SilentlyContinue"';
  Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1200);   // let the handles actually close before files are touched
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopTray();    // upgrading over a running copy would fail to replace it
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopTray();
  Result := True;
end;
