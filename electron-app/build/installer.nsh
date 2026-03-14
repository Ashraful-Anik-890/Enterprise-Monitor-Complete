; ═══════════════════════════════════════════════════════════════════════════════
; electron-app/build/installer.nsh
;
; Custom NSIS hooks for Enterprise Monitor — consumed by electron-builder v26
; via:  "nsis": { "include": "build/installer.nsh" }
;
; Hooks executed by electron-builder's NSIS template:
;   customInit       → .onInit  (before pages, every launch of the installer)
;   customInstall    → end of the Install Section
;   customUnInstall  → Uninstall Section
;
; Constants declared here shadow nothing in electron-builder's own template
; because they are all prefixed with EM_.
;
; NOTE: The License Agreement page is NOT injected from this file.
; electron-builder v26 renders it via the `nsis.license` field in package.json.
; Add the following to your package.json nsis block:
;
;   "license": "build/license.rtf"
;
; The license.rtf file must live at electron-app/build/license.rtf.
; ═══════════════════════════════════════════════════════════════════════════════


; ─── Project-wide constants ───────────────────────────────────────────────────
; Keep these in sync with package.json → build.productName / build.appId

!define EM_PRODUCT_NAME   "Enterprise Monitor"
!define EM_MAIN_EXE       "Enterprise Monitor.exe"
!define EM_BACKEND_EXE    "enterprise_monitor_backend.exe"

; HKCU Run key — no elevation required (requestedExecutionLevel = asInvoker).
; Electron's own app.setLoginItemSettings() also targets this path on Windows,
; so we use the identical value name to avoid a duplicate entry.
!define EM_REG_RUN_KEY    "Software\Microsoft\Windows\CurrentVersion\Run"
!define EM_REG_VALUE_NAME "Enterprise Monitor"

; User data directory (mirrors EM_DIR in main.ts)
; %LOCALAPPDATA% = $LOCALAPPDATA in NSIS
!define EM_DATA_DIR       "$LOCALAPPDATA\EnterpriseMonitor"


; ─── .onInit ─────────────────────────────────────────────────────────────────
; Runs before any installer page is displayed.
; Used to kill the running app so the installer does not lock files on update.
!macro customInit
  ; Silently terminate both processes. /F = force, no prompt.
  ; The exit code is discarded — if the process is not running that is fine.
  nsExec::ExecToStack 'taskkill /F /IM "${EM_BACKEND_EXE}"'
  Pop $0  ; discard exit code

  nsExec::ExecToStack 'taskkill /F /IM "${EM_MAIN_EXE}"'
  Pop $0

  ; Give Windows 1 second to release file locks before the installer
  ; tries to write into $INSTDIR.
  Sleep 1000
!macroend


; ─── Install Section (runs after files are copied) ───────────────────────────
!macro customInstall
  ; ── Step 1: Kill any backend that somehow survived customInit ────────────
  ; A second kill is cheap and eliminates the edge case where the user clicked
  ; "Back" and "Install" again after the first kill had already completed.
  DetailPrint "Ensuring backend process is not running..."
  nsExec::ExecToStack 'taskkill /F /IM "${EM_BACKEND_EXE}"'
  Pop $0

  ; ── Step 2: FORCE AUTOSTART — write the Electron app to the Registry Run key
  ; ─────────────────────────────────────────────────────────────────────────────
  ; WHY we do this from the installer rather than relying solely on
  ; app.setLoginItemSettings():
  ;   - app.setLoginItemSettings() runs only AFTER the first login + app launch.
  ;   - A Registry Run key written here fires immediately on the NEXT login —
  ;     even before the user has ever opened the app manually.
  ;   - This is the correct enterprise-deployment behaviour: the agent must be
  ;     running from the moment the OS boots, with zero user interaction.
  ;
  ; HKCU: no UAC elevation needed (requestedExecutionLevel = asInvoker).
  ; The value name matches what Electron's setLoginItemSettings writes on Windows,
  ; so the two mechanisms produce exactly ONE registry entry, not two.
  ;
  ; We do NOT pass --hidden or --autostart flags because main.ts does not parse
  ; them. The window hides to tray on close; on first launch it will appear
  ; once (expected behaviour for a first-run setup).
  DetailPrint "Registering autostart at Windows login..."
  WriteRegStr HKCU "${EM_REG_RUN_KEY}" \
              "${EM_REG_VALUE_NAME}"   \
              '"$INSTDIR\${EM_MAIN_EXE}"'

  DetailPrint "${EM_PRODUCT_NAME} will start automatically at next Windows login."
!macroend


; ─── Uninstall Section ────────────────────────────────────────────────────────
!macro customUnInstall
  ; ── Step 1: Kill both processes before electron-builder deletes $INSTDIR ──
  ; If the EXE is open, Windows cannot delete it. The uninstaller would either
  ; fail silently or leave a broken partial install behind.
  DetailPrint "Stopping ${EM_PRODUCT_NAME} processes..."
  nsExec::ExecToStack 'taskkill /F /IM "${EM_BACKEND_EXE}"'
  Pop $0

  nsExec::ExecToStack 'taskkill /F /IM "${EM_MAIN_EXE}"'
  Pop $0

  Sleep 1000

  ; ── Step 2: Remove the autostart Registry entry ───────────────────────────
  ; Without this, Windows logs an error on the next login when it cannot find
  ; the deleted EXE, and the user sees a "could not find application" popup.
  DetailPrint "Removing autostart Registry entry..."
  DeleteRegValue HKCU "${EM_REG_RUN_KEY}" "${EM_REG_VALUE_NAME}"

  ; ── Step 3: Remove stale port.info so a reinstall starts cleanly ─────────
  ; port.info lives outside $INSTDIR — electron-builder does not clean it.
  ; If it is left behind, a fresh install could connect to a ghost port.
  Delete "${EM_DATA_DIR}\port.info"

  ; ── Step 4: Offer to purge user data ─────────────────────────────────────
  ; Monitoring data (DB, screenshots, recordings, config) lives in
  ; %LOCALAPPDATA%\EnterpriseMonitor — outside $INSTDIR.
  ; electron-builder never touches it; we must handle it explicitly.
  ; We ask the user rather than deleting silently — this is correct UX for
  ; a monitoring tool where the collected data may be legally required.
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
