#define MyAppName "Enterprise Monitor"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Ashraful Anik"
#define MyAppExeName "Enterprise Monitor.exe"
#define BackendExeName "enterprise_monitor_backend.exe"
#define NssmExeName "nssm.exe"
#define ServiceName "EnterpriseMonitorBackend"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{7A6D80A1-34F5-4D09-B2FC-BE4B1CE93EFC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=admin
OutputDir=installer
OutputBaseFilename=Enterprise_Monitor_Setup
SetupIconFile=electron-app\resources\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\EnterpriseMonitor"
Name: "{commonappdata}\EnterpriseMonitor\backend"
Name: "{commonappdata}\EnterpriseMonitor\logs"
Name: "{commonappdata}\EnterpriseMonitor\videos"

[Files]
; Electron App
Source: "electron-app\release\win-unpacked\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "electron-app\release\win-unpacked\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Backend Service
Source: "backend-windows\dist\{#BackendExeName}"; DestDir: "{commonappdata}\EnterpriseMonitor\backend"; Flags: ignoreversion
Source: "resources\{#NssmExeName}"; DestDir: "{commonappdata}\EnterpriseMonitor\backend"; Flags: ignoreversion
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; ── Security: Lock Down Directories ──
Filename: "icacls"; Parameters: """{commonappdata}\EnterpriseMonitor\logs"" /inheritance:r /grant:r ""SYSTEM:(OI)(CI)F"" /grant:r ""Administrators:(OI)(CI)F"" /deny ""Users:(OI)(CI)(RX)"""; Flags: runhidden
Filename: "icacls"; Parameters: """{commonappdata}\EnterpriseMonitor\videos"" /inheritance:r /grant:r ""SYSTEM:(OI)(CI)F"" /grant:r ""Administrators:(OI)(CI)F"" /deny ""Users:(OI)(CI)(RX)"""; Flags: runhidden
Filename: "icacls"; Parameters: """{commonappdata}\EnterpriseMonitor"" /deny ""Users:(RX)"""; Flags: runhidden

; ── Stop/Remove Existing Service ──
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "stop ""{#ServiceName}"""; Flags: runhidden
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "remove ""{#ServiceName}"" confirm"; Flags: runhidden WaitUntilTerminated

; ── Install Setup NSSM Service ──
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "install ""{#ServiceName}"" ""{commonappdata}\EnterpriseMonitor\backend\{#BackendExeName}"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" DisplayName ""Enterprise Monitor Backend"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" Description ""Enterprise Monitor background agent — tracking and ERP sync."""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" Start SERVICE_AUTO_START"; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" ObjectName LocalSystem"; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" AppDirectory ""{commonappdata}\EnterpriseMonitor\backend"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" AppStdout ""{commonappdata}\EnterpriseMonitor\logs\backend_stdout.log"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" AppStderr ""{commonappdata}\EnterpriseMonitor\logs\backend_stderr.log"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" AppRotateFiles 1"; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "set ""{#ServiceName}"" AppRotateBytes 5242880"; Flags: runhidden WaitUntilTerminated

; ── Start Service ──
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "start ""{#ServiceName}"""; Flags: runhidden WaitUntilTerminated

; ── Launch App UI ──
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop and remove service on uninstall
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "stop ""{#ServiceName}"""; Flags: runhidden WaitUntilTerminated
Filename: "{commonappdata}\EnterpriseMonitor\backend\{#NssmExeName}"; Parameters: "remove ""{#ServiceName}"" confirm"; Flags: runhidden WaitUntilTerminated

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\EnterpriseMonitor\backend"
; Only removing backend dir to not erase user's logs/videos without prompt, but you could delete the whole "{commonappdata}\EnterpriseMonitor" if desired.
