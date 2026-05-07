; ═══════════════════════════════════════════════════════════════════════════════
; electron-app/build/installer.nsh
;
; CHANGES vs v5.3.0:
;   1. customUnInstall now cleans ALL three AppData locations:
;      a. $LOCALAPPDATA\EnterpriseMonitor       — monitoring DB, screenshots, logs
;      b. $APPDATA\enterprise-monitor           — electron-store (JWT, config)
;      c. $LOCALAPPDATA\enterprise-monitor-updater — electron-updater cache
;   2. Added $LOCALAPPDATA\Programs\enterprise-monitor cleanup (portable installs)
;   3. Fixed process kill ordering — Electron must die before backend to release
;      file handles on the SQLite WAL and port.info.
;   4. Removed ${isUpdated} guard on the data-purge prompt.
;      Update path (NSIS reinstall) never calls customUnInstall — that guard
;      was dead code that caused confusion. Removed entirely.
;   5. All RMDir calls are now guarded with existence checks to avoid
;      NSIS "directory not found" non-fatal errors polluting the log.
; ═══════════════════════════════════════════════════════════════════════════════


; ─── Project-wide constants ───────────────────────────────────────────────────
!define EM_PRODUCT_NAME   "Enterprise Monitor"
!define EM_MAIN_EXE       "Enterprise Monitor.exe"
!define EM_BACKEND_EXE    "enterprise_monitor_backend.exe"

!define EM_REG_RUN_KEY    "Software\Microsoft\Windows\CurrentVersion\Run"
!define EM_REG_VALUE_NAME "Enterprise Monitor"

; Our monitoring data: DB, screenshots, logs, config
!define EM_DATA_DIR       "$LOCALAPPDATA\EnterpriseMonitor"

; electron-store stores auth token, JWT secret, firstRunComplete, pendingUpdateVersion
; Directory name = package.json "name" field, lowercased, with dashes
!define EM_STORE_DIR      "$APPDATA\enterprise-monitor"

; electron-updater caches downloaded .exe and latest.yml here during update
!define EM_UPDATER_DIR    "$LOCALAPPDATA\enterprise-monitor-updater"

; electron-builder installs to this path in per-user (non-admin) mode
!define EM_PROGRAMS_DIR   "$LOCALAPPDATA\Programs\enterprise-monitor"


; ─── .onInit ─────────────────────────────────────────────────────────────────
; Runs before any installer page is shown.
; Kill order: Electron first (releases file handles), then backend.
!macro customInit
  DetailPrint "Stopping Enterprise Monitor processes (pre-install)..."

  ; Kill Electron first — it holds handles to the backend port.info and IPC
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0

  ; Kill backend process tree — /T ensures all child threads (pynput, OpenCV) die
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0

  ; 2500ms: Python teardown with OpenCV, mss, pynput, and SQLite WAL checkpoint
  Sleep 2500
!macroend


; ─── Install Section ─────────────────────────────────────────────────────────
!macro customInstall
  ; ── REDUNDANT KILL (critical for auto-update path) ───────────────────────
  ; By the time the user clicks Install, the Registry autostart may have
  ; respawned the backend. Kill again immediately before file extraction.
  DetailPrint "Ensuring processes stopped before file extraction..."

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0

  Sleep 1000

  ; ── SHADOW BACKUP (Layer 2 rollback) ─────────────────────────────────────
  DetailPrint "Creating shadow backup of current backend..."
  CreateDirectory "${EM_DATA_DIR}\backup"
  CopyFiles /SILENT "$INSTDIR\resources\backend\${EM_BACKEND_EXE}" "${EM_DATA_DIR}\backup\"

  ; ── AUTOSTART REGISTRY ───────────────────────────────────────────────────
  DetailPrint "Registering autostart at Windows login..."
  WriteRegStr HKCU "${EM_REG_RUN_KEY}" \
              "${EM_REG_VALUE_NAME}"   \
              '"$INSTDIR\${EM_MAIN_EXE}"'

  DetailPrint "${EM_PRODUCT_NAME} will start automatically at next Windows login."
!macroend


; ─── Uninstall Section ────────────────────────────────────────────────────────
!macro customUnInstall
  ; ── PROCESS KILL ─────────────────────────────────────────────────────────
  ; Kill Electron first (holds DB and port.info handles), then backend.
  DetailPrint "Stopping ${EM_PRODUCT_NAME} processes..."

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0

  Sleep 2500

  ; ── REGISTRY CLEANUP ─────────────────────────────────────────────────────
  DetailPrint "Removing autostart Registry entry..."
  DeleteRegValue HKCU "${EM_REG_RUN_KEY}" "${EM_REG_VALUE_NAME}"

  ; ── ELECTRON-UPDATER CACHE ───────────────────────────────────────────────
  ; This directory is created automatically by electron-updater when it
  ; downloads a pending update. It is NEVER cleaned by the default NSIS
  ; uninstaller — we must do it explicitly.
  DetailPrint "Removing electron-updater cache..."
  IfFileExists "${EM_UPDATER_DIR}\*.*" 0 +2
    RMDir /r "${EM_UPDATER_DIR}"

  ; ── ELECTRON-STORE APP DATA ──────────────────────────────────────────────
  ; electron-store writes to %APPDATA%\<package-name>\ by default.
  ; Contains: auth token, JWT secret (.jwt_secret), firstRunComplete flag,
  ; pendingUpdateVersion, currentVersionBeforeUpdate.
  ; All of this must be removed on uninstall — otherwise the next install
  ; inherits stale JWT secrets and token state from the old install.
  DetailPrint "Removing Electron application data (electron-store)..."
  IfFileExists "${EM_STORE_DIR}\*.*" 0 +2
    RMDir /r "${EM_STORE_DIR}"

  ; ── MONITORING DATA ──────────────────────────────────────────────────────
  ; Ask user whether to purge monitoring data.
  ; $LOCALAPPDATA\EnterpriseMonitor contains:
  ;   monitoring.db, screenshots\, videos\, logs\, config.json,
  ;   users.json, security_qa.json, .jwt_secret, .last_cleanup, port.info
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Remove all monitoring data?$\r$\n$\r$\n\
Enterprise Monitor stores its database, screenshots, screen recordings,$\r$\n\
and configuration in:$\r$\n$\r$\n\
    ${EM_DATA_DIR}$\r$\n$\r$\n\
Click YES to permanently delete this folder.$\r$\n\
Click NO to keep it (e.g. for audit/legal retention).$\r$\n$\r$\n\
This action cannot be undone." \
    IDYES purge_data IDNO keep_data

  purge_data:
    IfFileExists "${EM_DATA_DIR}\*.*" 0 +2
      RMDir /r "${EM_DATA_DIR}"
    DetailPrint "Monitoring data removed from ${EM_DATA_DIR}"
    Goto done_purge

  keep_data:
    ; Even if user keeps data, remove stale port.info so a future
    ; fresh install doesn't try to connect to a dead port.
    Delete "${EM_DATA_DIR}\port.info"
    Delete "${EM_DATA_DIR}\port.info.tmp"
    DetailPrint "Monitoring data retained at ${EM_DATA_DIR}"

  done_purge:

  ; ── PORTABLE INSTALL CLEANUP ─────────────────────────────────────────────
  ; electron-builder in per-user mode may also leave an entry under
  ; %LOCALAPPDATA%\Programs\enterprise-monitor. Clean it up if present.
  IfFileExists "${EM_PROGRAMS_DIR}\*.*" 0 +2
    RMDir /r "${EM_PROGRAMS_DIR}"

!macroend
