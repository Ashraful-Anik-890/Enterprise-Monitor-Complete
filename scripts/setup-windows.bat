@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

:: ============================================================
:: Enterprise Monitor — Windows Setup & Service Installer
:: Developed by Ashraful Anik
::
:: PREREQUISITES (run these manually BEFORE this script):
::   1.  Install Python 3.11+ (https://python.org) — add to PATH
::   2.  pip install pyinstaller mss opencv-python numpy fastapi
::       uvicorn[standard] pynput pywin32 psutil requests
::       python-jose[cryptography]
::   3.  Place nssm.exe in: resources\nssm.exe
::       Download from: https://nssm.cc/download (2.24 stable)
::   4.  Build the Electron frontend FIRST:
::         cd electron-app
::         npm install
::         npm run dist
::       This produces: electron-app\release\Enterprise Monitor Setup x.x.x.exe
::       Install that EXE before running this script.
::
:: HOW TO RUN:
::   Right-click this file → "Run as Administrator"
::   Or from an elevated CMD:
::     cd <project-root>
::     scripts\setup-windows.bat
:: ============================================================

echo.
echo ========================================================
echo   Enterprise Monitor — Backend Service Installer
echo ========================================================
echo.

:: ── Elevation check ──────────────────────────────────────────
net session >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] This script must be run as Administrator.
    echo         Right-click the script and choose "Run as Administrator".
    pause
    EXIT /B 1
)

:: ── Config ───────────────────────────────────────────────────
SET "PROJECT_ROOT=%~dp0.."
SET "BACKEND_DIR=%PROJECT_ROOT%\backend-windows"
SET "RESOURCES_DIR=%PROJECT_ROOT%\resources"
SET "NSSM=%RESOURCES_DIR%\nssm.exe"
SET "SERVICE_NAME=EnterpriseMonitorBackend"
SET "INSTALL_DIR=C:\ProgramData\EnterpriseMonitor"
SET "EXE_DEST=%INSTALL_DIR%\backend\enterprise_monitor_backend.exe"
SET "LOG_DIR=%INSTALL_DIR%\logs"
SET "VIDEO_DIR=%INSTALL_DIR%\videos"

echo [Step 1/7] Verifying prerequisites...
echo.

:: Check Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH.
    echo         Install from https://python.org and ensure "Add to PATH" is checked.
    pause
    EXIT /B 1
)
echo   [OK] Python found.

:: Check PyInstaller
pyinstaller --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller not found. Run: pip install pyinstaller
    pause
    EXIT /B 1
)
echo   [OK] PyInstaller found.

:: Check NSSM
IF NOT EXIST "%NSSM%" (
    echo [ERROR] nssm.exe not found at: %NSSM%
    echo         Download from https://nssm.cc/download and place in resources\
    pause
    EXIT /B 1
)
echo   [OK] nssm.exe found.

echo.
echo [Step 2/7] Creating install directories...
IF NOT EXIST "%INSTALL_DIR%"         MKDIR "%INSTALL_DIR%"
IF NOT EXIST "%INSTALL_DIR%\backend" MKDIR "%INSTALL_DIR%\backend"
IF NOT EXIST "%LOG_DIR%"             MKDIR "%LOG_DIR%"
IF NOT EXIST "%VIDEO_DIR%"           MKDIR "%VIDEO_DIR%"
echo   [OK] Directories created.

echo.
echo [Step 3/7] Building backend executable with PyInstaller...
echo   This may take 2-5 minutes on first run (bundling Python runtime).
echo.

CD /D "%BACKEND_DIR%"

:: Stop existing service before rebuilding to release file locks
"%NSSM%" status "%SERVICE_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo   Stopping existing service for rebuild...
    "%NSSM%" stop "%SERVICE_NAME%" confirm >nul 2>&1
    TIMEOUT /T 3 /NOBREAK >nul
)

:: Build with PyInstaller
:: --onefile      : single EXE (no folder sprawl)
:: --noconsole    : suppress the console window (runs silently as a service)
:: --name         : output EXE name
:: --hidden-import: modules PyInstaller cannot auto-detect
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name enterprise_monitor_backend ^
    --hidden-import=uvicorn.logging ^
    --hidden-import=uvicorn.loops ^
    --hidden-import=uvicorn.loops.auto ^
    --hidden-import=uvicorn.protocols ^
    --hidden-import=uvicorn.protocols.http ^
    --hidden-import=uvicorn.protocols.http.auto ^
    --hidden-import=uvicorn.protocols.websockets ^
    --hidden-import=uvicorn.protocols.websockets.auto ^
    --hidden-import=uvicorn.lifespan ^
    --hidden-import=uvicorn.lifespan.on ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse._win32 ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=win32gui ^
    --hidden-import=win32process ^
    --hidden-import=cv2 ^
    --hidden-import=mss ^
    --collect-all=cv2 ^
    --collect-all=mss ^
    main.py

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build FAILED. Check output above.
    pause
    EXIT /B 1
)
echo.
echo   [OK] PyInstaller build succeeded.

echo.
echo [Step 4/7] Copying executable to install directory...
COPY /Y "%BACKEND_DIR%\dist\enterprise_monitor_backend.exe" "%EXE_DEST%"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to copy EXE. Is it locked by a running service?
    pause
    EXIT /B 1
)
echo   [OK] EXE copied to %EXE_DEST%

echo.
echo [Step 5/7] Removing old service (if exists)...
"%NSSM%" status "%SERVICE_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    "%NSSM%" remove "%SERVICE_NAME%" confirm
    TIMEOUT /T 2 /NOBREAK >nul
    echo   [OK] Old service removed.
) ELSE (
    echo   [INFO] No existing service found, skipping removal.
)

echo.
echo [Step 6/7] Installing Windows Service via NSSM...

:: Install service — runs as LocalSystem (SYSTEM) account
"%NSSM%" install "%SERVICE_NAME%" "%EXE_DEST%"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] NSSM service installation failed.
    pause
    EXIT /B 1
)

:: Configure service properties
"%NSSM%" set "%SERVICE_NAME%" DisplayName    "Enterprise Monitor Backend"
"%NSSM%" set "%SERVICE_NAME%" Description    "Enterprise Monitor background agent — screen tracking, keylogging, and ERP sync."
"%NSSM%" set "%SERVICE_NAME%" Start          SERVICE_AUTO_START
"%NSSM%" set "%SERVICE_NAME%" ObjectName     LocalSystem
"%NSSM%" set "%SERVICE_NAME%" AppDirectory   "%INSTALL_DIR%\backend"
"%NSSM%" set "%SERVICE_NAME%" AppStdout      "%LOG_DIR%\backend_stdout.log"
"%NSSM%" set "%SERVICE_NAME%" AppStderr      "%LOG_DIR%\backend_stderr.log"
"%NSSM%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM%" set "%SERVICE_NAME%" AppRotateBytes 5242880

echo   [OK] Service installed and configured.

echo.
echo [Step 7/7] Starting the service...
"%NSSM%" start "%SERVICE_NAME%"
IF %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Service failed to start immediately.
    echo           Check logs at: %LOG_DIR%\
    echo           You can start it manually:  nssm start %SERVICE_NAME%
) ELSE (
    echo   [OK] Service started successfully.
)

echo.
TIMEOUT /T 3 /NOBREAK >nul
"%NSSM%" status "%SERVICE_NAME%"

echo.
echo ========================================================
echo   INSTALLATION COMPLETE
echo ========================================================
echo.
echo   Service name : %SERVICE_NAME%
echo   Executable   : %EXE_DEST%
echo   Logs         : %LOG_DIR%\
echo   Videos       : %VIDEO_DIR%\
echo   API port     : http://127.0.0.1:51235
echo.
echo   NEXT STEP: Install the Electron frontend
echo     electron-app\release\Enterprise Monitor Setup *.exe
echo.
echo   To manage the service:
echo     nssm start   %SERVICE_NAME%
echo     nssm stop    %SERVICE_NAME%
echo     nssm restart %SERVICE_NAME%
echo     nssm remove  %SERVICE_NAME% confirm
echo.
pause
ENDLOCAL
