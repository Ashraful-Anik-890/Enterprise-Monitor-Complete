@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

:: ============================================================
:: Enterprise Monitor — Windows Setup & Service Installer
:: Developed by Ashraful Anik
:: ============================================================

echo.
echo ========================================================
echo   Enterprise Monitor — Backend Service Installer
echo ========================================================
echo.

net session >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] This script must be run as Administrator.
    pause
    EXIT /B 1
)

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

IF EXIST "%BACKEND_DIR%\venv\Scripts\activate.bat" (
    echo   [INFO] Activating virtual environment in backend-windows\venv...
    CALL "%BACKEND_DIR%\venv\Scripts\activate.bat"
) ELSE IF EXIST "%PROJECT_ROOT%\venv\Scripts\activate.bat" (
    echo   [INFO] Activating virtual environment in project root...
    CALL "%PROJECT_ROOT%\venv\Scripts\activate.bat"
)


python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH.
    pause
    EXIT /B 1
)
echo   [OK] Python found.

python -m PyInstaller --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller not found. Run: pip install pyinstaller
    pause
    EXIT /B 1
)
echo   [OK] PyInstaller found.

IF NOT EXIST "%NSSM%" (
    echo [ERROR] nssm.exe not found at: %NSSM%
    pause
    EXIT /B 1
)
echo   [OK] nssm.exe found.

echo.
echo [Step 2/7] Creating install directories and locking permissions...
echo.

IF NOT EXIST "%INSTALL_DIR%"         MKDIR "%INSTALL_DIR%"
IF NOT EXIST "%INSTALL_DIR%\backend" MKDIR "%INSTALL_DIR%\backend"
IF NOT EXIST "%LOG_DIR%"             MKDIR "%LOG_DIR%"
IF NOT EXIST "%VIDEO_DIR%"           MKDIR "%VIDEO_DIR%"

:: ── LOCK LOG DIRECTORY ────────────────────────────────────────────────────
:: Reason: The monitored user must not discover they are being tracked.
:: If they can read backend.log, they see exactly what data is collected.
::
:: /inheritance:r          Remove all inherited ACEs — start from clean slate.
:: SYSTEM:(OI)(CI)F        Service account: Full Control + inheritable.
:: Administrators:(OI)(CI)F Local admins: Full Control + inheritable.
:: "Users":(OI)(CI)(RX)   Standard user group: explicitly DENIED read+execute.
::                         (OI)(CI) propagates the denial to subfolders and files.
::
:: After this: a standard user opening C:\ProgramData\EnterpriseMonitor\logs
:: gets "Access Denied" immediately. They cannot even see file names.
icacls "%LOG_DIR%" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F" /deny "Users:(OI)(CI)(RX)" >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Failed to set ACL on log dir. Run manually:
    echo          icacls "%LOG_DIR%" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F" /deny "Users:(OI)(CI)(RX)"
) ELSE (
    echo   [OK] Log directory locked — Users denied read access.
)

:: ── LOCK VIDEO DIRECTORY ──────────────────────────────────────────────────
:: Reason: Screen recording files must not be viewable by the monitored user.
icacls "%VIDEO_DIR%" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F" /deny "Users:(OI)(CI)(RX)" >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Failed to set ACL on video dir.
) ELSE (
    echo   [OK] Video directory locked — Users denied read access.
)

:: ── LOCK ENTIRE EnterpriseMonitor ROOT ────────────────────────────────────
:: Deny listing the root dir so users cannot even enumerate subfolders.
icacls "%INSTALL_DIR%" /deny "Users:(RX)" >nul 2>&1
echo   [OK] Install root access restricted.

echo   [OK] Directories created: %INSTALL_DIR%

echo.
echo [Step 3/7] Building backend executable with PyInstaller...
echo   This may take 3-8 minutes on first run.
echo.

CD /D "%BACKEND_DIR%"

"%NSSM%" status "%SERVICE_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo   Stopping existing service for rebuild...
    "%NSSM%" stop "%SERVICE_NAME%" confirm >nul 2>&1
    TIMEOUT /T 3 /NOBREAK >nul
)

:: Clean stale PyInstaller cache — avoids "Unable to commit changes" style errors
IF EXIST "%BACKEND_DIR%\build" (
    echo   Cleaning previous build cache...
    RMDIR /S /Q "%BACKEND_DIR%\build"
)
IF EXIST "%BACKEND_DIR%\dist" RMDIR /S /Q "%BACKEND_DIR%\dist"

:: ─── PyInstaller — ALL hidden imports documented ──────────────────────────
:: uvicorn.*          : loads loops/protocols via importlib string calls at runtime
:: anyio.*            : fastapi starlette async backend selected dynamically
:: multipart          : fastapi form/file upload (python-multipart)
:: pynput.*_win32     : pynput selects Windows platform backend at import time
:: win32*             : pywin32 COM/Win32 modules (app_tracker, screen_recorder)
:: cv2                : OpenCV (screen_recorder.py)
:: mss + mss.windows  : screen capture + Windows backend
:: numpy.*            : screen_recorder uses numpy BGRA→BGR array ops
:: passlib.handlers.* : passlib discovers bcrypt handler via plugin registry
:: jose.*             : python-jose JWT; backend selected dynamically
:: uiautomation       : browser_tracker — ships DLLs + XML config, collect-all needed
python -m PyInstaller ^
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
    --hidden-import=anyio ^
    --hidden-import=anyio.backends.asyncio ^
    --hidden-import=anyio._backends._asyncio ^
    --hidden-import=multipart ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse._win32 ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=win32gui ^
    --hidden-import=win32process ^
    --hidden-import=cv2 ^
    --hidden-import=mss ^
    --hidden-import=mss.windows ^
    --hidden-import=numpy ^
    --hidden-import=numpy.core._methods ^
    --hidden-import=numpy.lib.format ^
    --hidden-import=passlib ^
    --hidden-import=passlib.handlers.bcrypt ^
    --hidden-import=passlib.handlers.sha2_crypt ^
    --hidden-import=jose ^
    --hidden-import=jose.jwt ^
    --hidden-import=jose.backends ^
    --collect-all=cv2 ^
    --collect-all=mss ^
    --collect-all=uiautomation ^
    main.py

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build FAILED. Check output above.
    echo         Common fixes:
    echo           - Missing package: pip install ^<package^>
    echo           - Delete backend-windows\build\ and retry
    pause
    EXIT /B 1
)
echo   [OK] PyInstaller build succeeded.

echo.
echo [Step 4/7] Copying executable to install directory...
COPY /Y "%BACKEND_DIR%\dist\enterprise_monitor_backend.exe" "%EXE_DEST%"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to copy EXE. Run: nssm stop %SERVICE_NAME%  then retry.
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
    echo   [INFO] No existing service found.
)

echo.
echo [Step 6/7] Installing Windows Service via NSSM...
"%NSSM%" install "%SERVICE_NAME%" "%EXE_DEST%"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] NSSM service installation failed.
    pause
    EXIT /B 1
)

"%NSSM%" set "%SERVICE_NAME%" DisplayName    "Enterprise Monitor Backend"
"%NSSM%" set "%SERVICE_NAME%" Description    "Enterprise Monitor background agent — tracking and ERP sync."
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
    echo [WARNING] Service did not start immediately. Check: %LOG_DIR%\
    echo           Manual start: nssm start %SERVICE_NAME%
) ELSE (
    echo   [OK] Service started successfully.
)

TIMEOUT /T 3 /NOBREAK >nul
"%NSSM%" status "%SERVICE_NAME%"

echo.
echo ========================================================
echo   INSTALLATION COMPLETE
echo ========================================================
echo.
echo   Service : %SERVICE_NAME%
echo   EXE     : %EXE_DEST%
echo   Logs    : %LOG_DIR%\  [Users: ACCESS DENIED]
echo   Videos  : %VIDEO_DIR%\  [Users: ACCESS DENIED]
echo   API     : http://127.0.0.1:51235
echo.
echo   Manage:
echo     nssm start   %SERVICE_NAME%
echo     nssm stop    %SERVICE_NAME%
echo     nssm restart %SERVICE_NAME%
echo     nssm remove  %SERVICE_NAME% confirm
echo.
pause
ENDLOCAL