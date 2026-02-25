#define MyAppName      "Enterprise Monitor"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Ashraful Anik"
#define MyAppExeName   "Enterprise Monitor.exe"
#define BackendExeName "enterprise_monitor_backend.exe"
#define TaskName       "EnterpriseMonitorBackend"

; ─── WHY NO NSSM SERVICE ─────────────────────────────────────────────────────
; NSSM runs the backend as LocalSystem in Windows Session 0.
; Session 0 is ISOLATED from the user's desktop — mss.mss() captures a black
; screen, win32gui.GetForegroundWindow() always returns NULL, and Path.home()
; resolves to the SYSTEM profile (C:\Windows\system32\config\systemprofile).
; ALL monitoring features break silently. No code change is needed — the Python
; code already works correctly when run in the user's session (proven by dev).
;
; FIX: Use Task Scheduler with ONLOGON trigger instead.
; The task runs in the user's session → mss, win32gui, Path.home() all work.
; ─────────────────────────────────────────────────────────────────────────────

[Setup]
AppId={{7A6D80A1-34F5-4D09-B2FC-BE4B1CE93EFC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=Enterprise_Monitor_Setup
; If icon.ico doesn't exist yet, comment out this line and Inno Setup will use
; a default icon. DO NOT skip creating a real icon — see electron-app/resources/README.md
SetupIconFile=electron-app\resources\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UsePreviousAppDir=yes
DirExistsWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Code]
// ─────────────────────────────────────────────────────────────────────────────
// Pre-install: stop any running backend task and reset ACLs from a prior
// install. This prevents "access denied" errors on reinstall.
// ─────────────────────────────────────────────────────────────────────────────
procedure CleanupPriorInstall();
var
  DataPath : string;
  ResultCode: Integer;
begin
  // Kill any running backend process
  Exec('taskkill.exe', '/F /IM "' + ExpandConstant('{#BackendExeName}') + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Remove any existing scheduled task (ignores error if it doesn't exist)
  Exec('schtasks.exe', '/delete /tn "' + ExpandConstant('{#TaskName}') + '" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Reset ACLs on ProgramData directory so files can be overwritten
  DataPath := ExpandConstant('{commonappdata}\EnterpriseMonitor');
  if DirExists(DataPath) then
  begin
    Exec('takeown.exe', '/F "' + DataPath + '" /R /D Y',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /grant "Administrators:(OI)(CI)F" /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /remove:d "Users" /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /remove:d "Administrators" /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /remove:d "SYSTEM" /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    CleanupPriorInstall();
end;

// ─────────────────────────────────────────────────────────────────────────────
// Uninstall: reset ACLs first, then delete entire data directory.
// Without resetting ACLs, rmdir fails silently on locked folders.
// ─────────────────────────────────────────────────────────────────────────────
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath : string;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // ── 1. Kill the Electron GUI (removes ghost tray icon) ────────────────────
    Exec('taskkill.exe', '/F /IM "Enterprise Monitor.exe"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // ── 2. Kill the backend EXE ───────────────────────────────────────────────
    Exec('taskkill.exe', '/F /IM "' + ExpandConstant('{#BackendExeName}') + '"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // ── 3. Remove the scheduled task ─────────────────────────────────────────
    Exec('schtasks.exe', '/delete /tn "' + ExpandConstant('{#TaskName}') + '" /f',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // ── 4. Reset ACLs so the locked backend folder can be deleted ────────────
    DataPath := ExpandConstant('{commonappdata}\EnterpriseMonitor');
    Exec('takeown.exe', '/F "' + DataPath + '" /R /D Y',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /reset /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls.exe', '"' + DataPath + '" /grant "Administrators:(OI)(CI)F" /T /C',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{commonappdata}\EnterpriseMonitor');
    if DirExists(DataPath) then
      DelTree(DataPath, True, True, True);
  end;
end;

[Dirs]
; uninsneveruninstall: Code section handles deletion after ACL reset.
; Without this flag Inno Setup rmdir's BEFORE our ACL reset → fails silently.
Name: "{commonappdata}\EnterpriseMonitor";                  Flags: uninsneveruninstall
Name: "{commonappdata}\EnterpriseMonitor\backend";          Flags: uninsneveruninstall

[Files]
; ── Electron App (produced by: cd electron-app && npm run dist:dir) ──────────
Source: "electron-app\release\win-unpacked\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "electron-app\release\win-unpacked\*";               DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── Backend onedir folder (produced by: scripts\setup-windows.bat or PyInstaller) ──
; Copy every file from dist\enterprise_monitor_backend\ (the EXE + all DLLs,
; .pyd extensions, data files, etc.). recursesubdirs handles nested folders
; that collect_all('cv2'), collect_all('mss'), collect_all('uiautomation') emit.
Source: "backend-windows\dist\enterprise_monitor_backend\{#BackendExeName}"; DestDir: "{commonappdata}\EnterpriseMonitor\backend"; Flags: ignoreversion
Source: "backend-windows\dist\enterprise_monitor_backend\*";                 DestDir: "{commonappdata}\EnterpriseMonitor\backend"; Flags: ignoreversion recursesubdirs createallsubdirs


; Backend EXE (produced by: setup-windows.bat or PyInstaller directly)
Source: "backend-windows\dist\enterprise_monitor_backend\{#BackendExeName}"; DestDir: "{commonappdata}\EnterpriseMonitor\backend"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";                        Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";                  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 1. Lock the backend EXE directory (SYSTEM + Admins only)
Filename: "icacls"; \
  Parameters: """{commonappdata}\EnterpriseMonitor\backend"" /inheritance:r /grant:r ""SYSTEM:(OI)(CI)F"" /grant:r ""Administrators:(OI)(CI)F"""; \
  Flags: runhidden waituntilterminated

; 2. Register Task Scheduler — 5s delay instead of 30s
Filename: "schtasks.exe"; \
  Parameters: "/create /tn ""{#TaskName}"" /tr """"""{commonappdata}\EnterpriseMonitor\backend\{#BackendExeName}"""""" /sc ONLOGON /rl HIGHEST /delay 0000:05 /f"; \
  Flags: runhidden waituntilterminated

; 3. Start the backend immediately
Filename: "schtasks.exe"; \
  Parameters: "/run /tn ""{#TaskName}"""; \
  Flags: runhidden waituntilterminated

; 4. Wait 8s for uvicorn to bind, then launch the GUI
Filename: "{sys}\timeout.exe"; \
  Parameters: "8 /nobreak"; \
  Flags: runhidden waituntilterminated

Filename: "{app}\{#MyAppExeName}"; \
  Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the scheduled task immediately on uninstall
; (The Code section handles task deletion and folder cleanup)
Filename: "schtasks.exe"; \
  Parameters: "/end /tn ""{#TaskName}"""; \
  Flags: runhidden; RunOnceId: "EndTask"

; [UninstallDelete] intentionally omitted.
; CurUninstallStepChanged handles it: resets ACLs first, then DelTree.
; Relying on [UninstallDelete] alone would fail on ACL-locked directories.
