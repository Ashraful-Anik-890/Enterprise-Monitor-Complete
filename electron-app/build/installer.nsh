; ═══════════════════════════════════════════════════════════════════════════════
; electron-app/build/installer.nsh
;
; CHANGES vs previous version:
;   1. All taskkill calls now include /T (terminate entire process tree)
;      Without /T, COM objects and pynput hooks survive and hold file locks.
;   2. Sleep increased from 1000ms to 2500ms
;      Python teardown (OpenCV, mss, SQLite WAL) takes up to 2-3s on load.
;   3. Redundant kill added at the TOP of customInstall
;      Reason: by the time user clicks Install, 30-60s may have passed since
;      .onInit. The Registry autostart key may have respawned the backend.
;   4. Shadow backup of backend binary before extraction (Layer 2 rollback)
; ═══════════════════════════════════════════════════════════════════════════════


; ─── Project-wide constants ───────────────────────────────────────────────────
!define EM_PRODUCT_NAME   "Enterprise Monitor"
!define EM_MAIN_EXE       "Enterprise Monitor.exe"
!define EM_BACKEND_EXE    "enterprise_monitor_backend.exe"

!define EM_REG_RUN_KEY    "Software\Microsoft\Windows\CurrentVersion\Run"
!define EM_REG_VALUE_NAME "Enterprise Monitor"

!define EM_DATA_DIR       "$LOCALAPPDATA\EnterpriseMonitor"


; ─── .onInit ─────────────────────────────────────────────────────────────────
; Runs before any installer page is shown.
; /T kills the entire process tree, not just the named executable.
; This catches COM objects, pynput hooks, and any child threads Python spawned.
!macro customInit
  DetailPrint "Stopping Enterprise Monitor processes (pre-install)..."

  ; Kill backend process tree — /T ensures all child threads die too
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0  ; discard exit code — it is non-zero if process was not running (that is fine)

  ; Kill Electron process tree
  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0

  ; 2500ms: Python teardown with OpenCV, mss, pynput, and SQLite WAL
  ; checkpoint can take 2-3 seconds on a loaded machine.
  ; Previous value of 1000ms was insufficient on slow machines.
  Sleep 2500
!macroend


; ─── Install Section ─────────────────────────────────────────────────────────
!macro customInstall
  ; ── REDUNDANT KILL (critical for auto-update path) ───────────────────────
  ; Why: When electron-updater downloads an update and the user clicks
  ; "Install Now", .onInit ran when the NSIS installer first launched.
  ; By the time the user confirmed and this macro runs, time has passed.
  ; The Windows Registry Run key from the previous install may have fired
  ; and respawned the backend. We kill again here, immediately before
  ; electron-builder starts copying files into $INSTDIR.
  DetailPrint "Ensuring backend is stopped before file extraction..."

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0

  ; Brief pause to release remaining file handles
  Sleep 1000

  ; ── SHADOW BACKUP (Layer 2 rollback) ─────────────────────────────────────
  ; Before extracting new files, back up the current backend binary.
  ; If the update fails or the new binary is corrupted, Electron's startup
  ; integrity check can restore from this backup automatically.
  DetailPrint "Creating shadow backup of current backend..."
  CreateDirectory "${EM_DATA_DIR}\backup"
  CopyFiles /SILENT "$INSTDIR\resources\backend\${EM_BACKEND_EXE}" "${EM_DATA_DIR}\backup\"

  ; ── AUTOSTART REGISTRY (write once, survives updates) ────────────────────
  ; This writes the Electron app to the Windows Registry Run key so it starts
  ; automatically on every user login. electron-builder's setLoginItemSettings
  ; also does this at runtime, but only after the first launch. Writing it here
  ; guarantees monitoring starts immediately after the very first install,
  ; even before the admin opens the app manually.
  DetailPrint "Registering autostart at Windows login..."
  WriteRegStr HKCU "${EM_REG_RUN_KEY}" \
              "${EM_REG_VALUE_NAME}"   \
              '"$INSTDIR\${EM_MAIN_EXE}"'

  DetailPrint "${EM_PRODUCT_NAME} will start automatically at next Windows login."
!macroend


; ─── Uninstall Section ────────────────────────────────────────────────────────
!macro customUnInstall
  ; Kill both processes before electron-builder deletes $INSTDIR.
  ; /T is critical here: if the backend spawned any child processes during
  ; its final data flush, those children also hold handles to $INSTDIR files.
  DetailPrint "Stopping ${EM_PRODUCT_NAME} processes..."

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_BACKEND_EXE}"'
  Pop $0

  nsExec::ExecToStack 'taskkill /F /T /IM "${EM_MAIN_EXE}"'
  Pop $0

  Sleep 2500

  ; Remove the autostart Registry entry.
  ; Without this, Windows logs an error on the next login when it cannot
  ; find the deleted EXE, and shows a "could not find application" popup.
  DetailPrint "Removing autostart Registry entry..."
  DeleteRegValue HKCU "${EM_REG_RUN_KEY}" "${EM_REG_VALUE_NAME}"

  ; Remove stale port.info so a fresh install starts cleanly.
  Delete "${EM_DATA_DIR}\port.info"

  ; Clean up shadow backup directory
  RMDir /r "${EM_DATA_DIR}\backup"

  ; ── REINSTALL / UPDATE CHECK ────────────────────────────────────────────────
  ; If we are performing an update (reinstalling the app), we skip the 
  ; data removal prompt entirely to prevent accidental loss of monitoring logs.
  ${if} ${isUpdated}
    DetailPrint "Update detected — preserving user data and skipping prompt."
    Goto done_purge
  ${endif}

  ; Offer to purge monitoring data (database, screenshots, recordings).
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
    RMDir /r "${EM_DATA_DIR}"
    DetailPrint "User data removed from ${EM_DATA_DIR}"
    Goto done_purge

  keep_data:
    DetailPrint "User data retained at ${EM_DATA_DIR}"

  done_purge:
!macroend
