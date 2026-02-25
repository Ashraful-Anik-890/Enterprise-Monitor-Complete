@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

echo.
echo ========================================================
echo   Enterprise Monitor -- Backend Builder
echo ========================================================
echo.

:: ── Elevation check ──────────────────────────────────────────────────────────
net session >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] This script must be run as Administrator.
    echo         Right-click the .bat file and choose "Run as administrator".
    pause
    EXIT /B 1
)

SET "PROJECT_ROOT=%~dp0.."
SET "BACKEND_DIR=%PROJECT_ROOT%\backend-windows"
SET "TASK_NAME=EnterpriseMonitorBackend"
SET "INSTALL_DIR=C:\ProgramData\EnterpriseMonitor"

:: ONEDIR: PyInstaller outputs a folder, not a single EXE.
:: Source is the entire dist\enterprise_monitor_backend\ folder.
:: The EXE inside it is the entry point for Task Scheduler.
SET "DIST_DIR=%BACKEND_DIR%\dist\enterprise_monitor_backend"
SET "EXE_SRC=%DIST_DIR%\enterprise_monitor_backend.exe"
SET "BACKEND_DEST=%INSTALL_DIR%\backend"
SET "EXE_DEST=%BACKEND_DEST%\enterprise_monitor_backend.exe"
SET "PYTHON_EXE="

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 1 — FIND PYTHON
:: ─────────────────────────────────────────────────────────────────────────────
echo [1/5] Locating Python...

FOR %%V IN (314 313 312 311 310 39) DO (
    IF NOT DEFINED PYTHON_EXE (
        IF EXIST "C:\Program Files\Python%%V\python.exe" (
            SET "PYTHON_EXE=C:\Program Files\Python%%V\python.exe"
        )
    )
)

FOR %%V IN (314 313 312 311 310 39) DO (
    IF NOT DEFINED PYTHON_EXE (
        IF EXIST "C:\Program Files (x86)\Python%%V\python.exe" (
            SET "PYTHON_EXE=C:\Program Files (x86)\Python%%V\python.exe"
        )
    )
)

IF NOT DEFINED PYTHON_EXE (
    where py >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        FOR /F "delims=" %%i IN ('py -c "import sys; print(sys.executable)" 2^>nul') DO (
            IF NOT DEFINED PYTHON_EXE SET "PYTHON_EXE=%%i"
        )
    )
)

IF NOT DEFINED PYTHON_EXE (
    FOR /F "delims=" %%i IN ('where python 2^>nul') DO (
        IF NOT DEFINED PYTHON_EXE SET "PYTHON_EXE=%%i"
    )
)

IF NOT DEFINED PYTHON_EXE (
    echo.
    echo [ERROR] Python not found.
    echo   Reinstall Python with "Install for all users" checked.
    pause
    EXIT /B 1
)

echo   [OK] Python: !PYTHON_EXE!

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 2 — BUILD WITH PYINSTALLER (ONEDIR)
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [2/5] Building backend (onedir)...

cd /d "%BACKEND_DIR%"

IF EXIST "enterprise_monitor_backend.spec" (
    echo   [INFO] Using enterprise_monitor_backend.spec
    "!PYTHON_EXE!" -m PyInstaller enterprise_monitor_backend.spec
) ELSE (
    echo   [INFO] No .spec found, using inline flags (onedir)
    "!PYTHON_EXE!" -m PyInstaller ^
        --onedir ^
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
)

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build FAILED. Read the output above carefully.
    echo   Common fixes:
    echo     Missing package : "!PYTHON_EXE!" -m pip install ^<package-name^>
    echo     Stale cache     : delete backend-windows\build\ and retry
    pause
    EXIT /B 1
)

IF NOT EXIST "%EXE_SRC%" (
    echo [ERROR] Build succeeded but EXE missing: %EXE_SRC%
    pause
    EXIT /B 1
)
echo   [OK] Built: %DIST_DIR%

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 3 — DEPLOY FOLDER TO PROGRAMDATA
::
:: ONEDIR: copy the entire dist\enterprise_monitor_backend\ folder.
:: We clean the destination first so stale DLLs from a previous build
:: don't accumulate (important when upgrading OpenCV / uiautomation).
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [3/5] Deploying backend folder...

IF NOT EXIST "%INSTALL_DIR%" MKDIR "%INSTALL_DIR%"

:: Kill any running backend before we try to overwrite its DLLs/EXE.
taskkill /F /IM enterprise_monitor_backend.exe >nul 2>&1
TIMEOUT /T 2 /NOBREAK >nul

:: Remove stale destination folder cleanly.
IF EXIST "%BACKEND_DEST%" (
    :: Reset ACLs first so our own icacls-locked folder is deletable.
    icacls "%BACKEND_DEST%" /reset /T /C >nul 2>&1
    rmdir /S /Q "%BACKEND_DEST%" >nul 2>&1
)

:: Lock only the backend folder (SYSTEM + Admins only — no /deny needed).
MKDIR "%BACKEND_DEST%"
icacls "%BACKEND_DEST%" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F" >nul 2>&1

:: Copy entire dist folder into destination.
xcopy /E /I /Y /Q "%DIST_DIR%\*" "%BACKEND_DEST%\" >nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to copy backend folder to %BACKEND_DEST%
    pause
    EXIT /B 1
)

IF NOT EXIST "%EXE_DEST%" (
    echo [ERROR] Deploy succeeded but EXE missing at: %EXE_DEST%
    pause
    EXIT /B 1
)
echo   [OK] Deployed to %BACKEND_DEST%

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 4 — REGISTER TASK SCHEDULER
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [4/5] Registering Task Scheduler (ONLOGON, user session)...

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    echo   [OK] Removed old task.
)

schtasks /create /tn "%TASK_NAME%" /tr "\"%EXE_DEST%\"" /sc ONLOGON /rl HIGHEST /delay 0000:05 /f

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Task Scheduler registration failed.
    pause
    EXIT /B 1
)
echo   [OK] Task registered: %TASK_NAME%

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 5 — START NOW
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [5/5] Starting backend for this session...
schtasks /run /tn "%TASK_NAME%"
TIMEOUT /T 8 /NOBREAK >nul

:: Read dynamic port from port.info (backend writes it on startup)
SET "PORT_FILE=%LOCALAPPDATA%\EnterpriseMonitor\port.info"
SET "BACKEND_PORT="
IF EXIST "%PORT_FILE%" (
    FOR /F "usebackq delims=" %%P IN ("%PORT_FILE%") DO SET "BACKEND_PORT=%%P"
)
IF NOT DEFINED BACKEND_PORT SET "BACKEND_PORT=51235"

curl -s --max-time 5 http://127.0.0.1:!BACKEND_PORT!/health >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo   [OK] API healthy: http://127.0.0.1:!BACKEND_PORT!/health
) ELSE (
    echo   [WARN] API not yet responding. Wait 30s then check:
    echo          Check port in: %PORT_FILE%
    echo          curl http://127.0.0.1:^<port^>/health
)

echo.
echo ========================================================
echo   DONE
echo ========================================================
echo   Task  : %TASK_NAME%
echo   EXE   : %EXE_DEST%
echo   Port  : !BACKEND_PORT! (dynamic — see %PORT_FILE%)
echo   Data  : %%LOCALAPPDATA%%\EnterpriseMonitor\
echo.
echo   Task Manager should now show ONE enterprise_monitor_backend.exe
echo   running under YOUR username. If you still see two, check:
echo     schtasks /query /tn "%TASK_NAME%" /fo LIST
echo.
pause
ENDLOCAL