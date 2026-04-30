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
:: STEP 1b — CLEANUP
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [1b/5] Cleaning build environment...

cd /d "%BACKEND_DIR%"
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist dist_obf rmdir /s /q dist_obf
if exist __pycache__ rmdir /s /q __pycache__
echo   [OK] Backend build folders cleared

echo   [OK] Workspace is clean

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 2a — OBFUSCATE WITH PYARMOR
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [2a/5] Obfuscating Python source with PyArmor...

cd /d "%BACKEND_DIR%"

:: Clean previous
if exist dist_obf rmdir /s /q dist_obf
mkdir dist_obf

:: Copy everything to staging area EXCEPT build folders
echo   Staging source files...
robocopy . dist_obf /E /NJH /NJS /NDL /NC /NS /MT /XF .DS_Store /XD dist dist_obf build __pycache__

:: Obfuscate only the sensitive modules (under 32KB trial limit)
:: These will overwrite the plain-text versions in the dist_obf folder
echo   Obfuscating sensitive modules...
"!PYTHON_EXE!" -m pyarmor.cli gen --output dist_obf --recursive ^
    main.py url.py auth\ monitoring\ utils\


IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyArmor obfuscation FAILED.
    pause
    EXIT /B 1
)

echo   [OK] Obfuscation complete: %BACKEND_DIR%\dist_obf

:: ─────────────────────────────────────────────────────────────────────────────
:: STEP 2b — BUILD PYINSTALLER FROM OBFUSCATED OUTPUT
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo [2b/5] Building backend from obfuscated source...

cd /d "%BACKEND_DIR%\dist_obf"

:: Copy the spec file into obfuscated dir (paths are relative)
copy /Y "%BACKEND_DIR%\enterprise_monitor_backend.spec" .

:: Run PyInstaller on obfuscated main.py
"!PYTHON_EXE!" -m PyInstaller enterprise_monitor_backend.spec

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build FAILED on obfuscated source.
    pause
    EXIT /B 1
)

:: Move output back to expected location
IF EXIST "%BACKEND_DIR%\dist" RMDIR /S /Q "%BACKEND_DIR%\dist"
MOVE "dist" "%BACKEND_DIR%\dist"

cd /d "%BACKEND_DIR%"
echo   [OK] Protected binary built: %DIST_DIR%

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