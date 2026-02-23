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
SET "EXE_SRC=%BACKEND_DIR%\dist\enterprise_monitor_backend.exe"
SET "EXE_DEST=%INSTALL_DIR%\backend\enterprise_monitor_backend.exe"
SET "PYTHON_EXE="

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 1 — FIND PYTHON
:: Priority order:
::   1. System-wide install in Program Files (correct, works under admin)
::   2. py.exe launcher (resolves to whichever Python it knows)
::   3. PATH lookup
::   4. Fail with clear instructions
:: ─────────────────────────────────────────────────────────────────────────────
echo [1/5] Locating Python...

:: Check all common system-wide Python versions (Program Files = admin-visible)
FOR %%V IN (314 313 312 311 310 39) DO (
    IF NOT DEFINED PYTHON_EXE (
        IF EXIST "C:\Program Files\Python%%V\python.exe" (
            SET "PYTHON_EXE=C:\Program Files\Python%%V\python.exe"
        )
    )
)

:: Also check Program Files (x86) for 32-bit installs
FOR %%V IN (314 313 312 311 310 39) DO (
    IF NOT DEFINED PYTHON_EXE (
        IF EXIST "C:\Program Files (x86)\Python%%V\python.exe" (
            SET "PYTHON_EXE=C:\Program Files (x86)\Python%%V\python.exe"
        )
    )
)

:: Try py launcher — it knows all installs including system-wide ones
IF NOT DEFINED PYTHON_EXE (
    where py >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        FOR /F "delims=" %%i IN ('py -c "import sys; print(sys.executable)" 2^>nul') DO (
            IF NOT DEFINED PYTHON_EXE SET "PYTHON_EXE=%%i"
        )
    )
)

:: Last resort: whatever "python" resolves to in admin PATH
IF NOT DEFINED PYTHON_EXE (
    FOR /F "delims=" %%i IN ('where python 2^>nul') DO (
        IF NOT DEFINED PYTHON_EXE SET "PYTHON_EXE=%%i"
    )
)

IF NOT DEFINED PYTHON_EXE (
    echo.
    echo [ERROR] Python not found.
    echo.
    echo   Your Python is installed USER-ONLY and is invisible to admin context.
    echo   FIX: Reinstall Python and check "Install for all users":
    echo     1. Download from https://python.org/downloads
    echo     2. Run installer
    echo     3. Click "Customize installation"
    echo     4. CHECK "Install for all users"  ^<--- THIS IS THE FIX
    echo     5. Finish install
    echo     6. Then run: pip install pyinstaller ^(in admin cmd^)
    echo.
    pause
    EXIT /B 1
)

echo   [OK] Python: !PYTHON_EXE!

:: Confirm PyInstaller is visible to THIS python
"!PYTHON_EXE!" -m PyInstaller --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller not found for: !PYTHON_EXE!
    echo.
    echo   Python was found but PyInstaller is not installed for it.
    echo   Run this command in an ADMIN cmd window:
    echo.
    echo     "!PYTHON_EXE!" -m pip install pyinstaller
    echo.
    echo   If you want ALL packages installed system-wide run:
    echo     "!PYTHON_EXE!" -m pip install pyinstaller fastapi uvicorn[standard] ^
    echo       python-jose[cryptography] passlib[bcrypt] mss Pillow pywin32 ^
    echo       psutil pyperclip requests tzdata uiautomation pynput opencv-python ^
    echo       numpy python-multipart
    echo.
    pause
    EXIT /B 1
)

FOR /F "delims=" %%v IN ('"!PYTHON_EXE!" -m PyInstaller --version 2^>nul') DO SET "PYI_VER=%%v"
echo   [OK] PyInstaller !PYI_VER! confirmed.

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 2 — BUILD EXE
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [2/5] Building backend EXE...
echo   Source : %BACKEND_DIR%\main.py
echo   Output : %EXE_SRC%
echo.

CD /D "%BACKEND_DIR%"

:: Kill running backend so the EXE file isn't locked
taskkill /F /IM enterprise_monitor_backend.exe >nul 2>&1

:: Stop existing task so it doesn't hold file locks
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo   Stopping existing task for rebuild...
    schtasks /end /tn "%TASK_NAME%" >nul 2>&1
    TIMEOUT /T 3 /NOBREAK >nul
)

:: Clean stale PyInstaller cache (prevents "unable to commit changes" errors)
IF EXIST "%BACKEND_DIR%\build" (
    echo   Cleaning build cache...
    RMDIR /S /Q "%BACKEND_DIR%\build"
)
IF EXIST "%BACKEND_DIR%\dist" RMDIR /S /Q "%BACKEND_DIR%\dist"

:: Use .spec file if present, otherwise inline flags
IF EXIST "%BACKEND_DIR%\enterprise_monitor_backend.spec" (
    echo   [INFO] Using enterprise_monitor_backend.spec
    "!PYTHON_EXE!" -m PyInstaller enterprise_monitor_backend.spec
) ELSE (
    echo   [INFO] No .spec found, using inline flags
    "!PYTHON_EXE!" -m PyInstaller ^
        --onefile ^
        --console ^
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
    echo [ERROR] Build claimed success but EXE missing: %EXE_SRC%
    pause
    EXIT /B 1
)
echo   [OK] EXE built: %EXE_SRC%

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 3 — DEPLOY EXE TO PROGRAMDATA
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [3/5] Deploying EXE...

IF NOT EXIST "%INSTALL_DIR%"         MKDIR "%INSTALL_DIR%"
IF NOT EXIST "%INSTALL_DIR%\backend" MKDIR "%INSTALL_DIR%\backend"

:: Correct ACL: no /deny flag. Absence of Allow = implicit Deny.
:: /deny "Users" would also deny Administrators (they are in Users group).
icacls "%INSTALL_DIR%\backend" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F" >nul 2>&1

COPY /Y "%EXE_SRC%" "%EXE_DEST%"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to copy EXE. It may be locked by a running process.
    echo         Run: taskkill /F /IM enterprise_monitor_backend.exe
    pause
    EXIT /B 1
)
echo   [OK] Deployed to %EXE_DEST%

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 4 — REGISTER TASK SCHEDULER
:: Runs in the USER session (not Session 0) — this is why monitoring works.
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [4/5] Registering Task Scheduler (ONLOGON, user session)...

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    echo   [OK] Removed old task.
)

schtasks /create /tn "%TASK_NAME%" /tr "\"%EXE_DEST%\"" /sc ONLOGON /rl HIGHEST /delay 0000:30 /f

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

curl -s --max-time 5 http://127.0.0.1:51235/health >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    echo   [OK] API healthy: http://127.0.0.1:51235/health
) ELSE (
    echo   [WARN] API not yet responding. Wait 30s then check:
    echo          curl http://127.0.0.1:51235/health
)

echo.
echo ========================================================
echo   DONE
echo ========================================================
echo   Task  : %TASK_NAME%
echo   EXE   : %EXE_DEST%
echo   API   : http://127.0.0.1:51235
echo   Data  : %%LOCALAPPDATA%%\EnterpriseMonitor\
echo.
echo   IMPORTANT: Open Task Manager ^> Details tab
echo   enterprise_monitor_backend.exe must show YOUR username
echo   NOT "SYSTEM". If it shows SYSTEM, the old NSSM service
echo   is still alive. Run: sc delete EnterpriseMonitorBackend
echo.
pause
ENDLOCAL