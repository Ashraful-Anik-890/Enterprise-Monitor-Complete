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
:: STEP 3 — CLEANUP STALE TASK SCHEDULER (from previous script versions)
::
:: Previous versions of this script registered a Task Scheduler job.
:: That conflicts with electron-builder's model where Electron spawns the
:: backend as a child process. Delete any stale task to prevent duplicates.
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [3/3] Cleaning up stale Task Scheduler entry (if any)...

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    echo   [OK] Removed stale scheduled task "%TASK_NAME%".
) ELSE (
    echo   [OK] No stale task found — nothing to clean.
)

:: Also kill any orphan backend that may be running from the old task
taskkill /F /IM enterprise_monitor_backend.exe >nul 2>&1

echo.
echo ========================================================
echo   DONE — Backend built successfully!
echo ========================================================
echo   Output : %DIST_DIR%
echo.
echo   Next step:
echo     cd ..\electron-app
echo     npm run dist
echo.
echo   electron-builder will bundle the backend from:
echo     %DIST_DIR%
echo   into the installer via extraResources.
echo.
echo   Electron manages the backend lifecycle (spawn/kill).
echo   NO Task Scheduler or manual start needed.
echo.
pause
ENDLOCAL