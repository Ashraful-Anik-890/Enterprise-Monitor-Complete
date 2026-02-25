# 🔧 Build & Implementation Guide

Step-by-step guide to build **Enterprise Monitor** into a distributable Windows installer.

---

## Prerequisites

| Tool | Version | Purpose | Download |
|---|---|---|---|
| **Python** | 3.10+ | Backend runtime + PyInstaller | [python.org](https://www.python.org/downloads/) |
| **Node.js** | 18+ | Electron build tooling | [nodejs.org](https://nodejs.org/) |
| **Inno Setup** | 6.x | Windows installer compiler | [jrsoftware.org](https://jrsoftware.org/isdl.php) |
| **Git** | any | Version control | [git-scm.com](https://git-scm.com/) |

> **Important:** Install Python with **"Install for all users"** checked and **"Add to PATH"** enabled.

---

## Step 1 — Install Python Dependencies

```powershell
cd backend-windows
pip install -r requirements.txt
```

**Key packages installed:** `fastapi`, `uvicorn`, `pywin32`, `uiautomation`, `pynput`, `mss`, `opencv-python`, `python-jose`, `passlib`, `pyinstaller`

Verify PyInstaller is accessible:

```powershell
python -m PyInstaller --version
```

---

## Step 2 — Build Backend Executable (PyInstaller)

### Option A: Using the `.spec` file (recommended)

```powershell
cd backend-windows
python -m PyInstaller enterprise_monitor_backend.spec
```

### Option B: Using the setup script (builds + deploys + registers Task Scheduler)

```powershell
# Run as Administrator
scripts\setup-windows.bat
```

> This creates `backend-windows/dist/enterprise_monitor_backend/` — a folder containing:
> - `enterprise_monitor_backend.exe` (entry point)
> - All DLLs, `.pyd` extensions, and data files

### Verify the build

```powershell
# Should start the backend and create port.info
backend-windows\dist\enterprise_monitor_backend\enterprise_monitor_backend.exe

# In another terminal, verify it's running:
curl http://127.0.0.1:51235/health
# Expected: {"status":"healthy","platform":"windows","timestamp":"..."}
```

### Common build issues

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'X'` | `pip install X` then rebuild |
| `PyInstaller not found` | `pip install pyinstaller` |
| Build succeeds but EXE crashes silently | Check `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log` |
| `comtypes` cache errors | Delete `%LOCALAPPDATA%\EnterpriseMonitor\comtypes_cache\` and retry |
| Stale build artifacts | Delete `backend-windows\build\` and `backend-windows\dist\` then rebuild |

---

## Step 3 — Install Electron Dependencies

```powershell
cd electron-app
npm install
```

---

## Step 4 — Test in Development Mode

```powershell
cd electron-app
npm start
```

This will:
1. Compile TypeScript (`main.ts`, `preload.ts`)
2. Launch the Electron window
3. Auto-spawn the backend (uses `python main.py` if no built EXE found)
4. Perform the dynamic port handshake

> **Default login:** `admin` / `admin`

---

## Step 5 — Package Electron App

```powershell
cd electron-app
npm run dist:dir
```

This produces: `electron-app/release/win-unpacked/` containing:
- `Enterprise Monitor.exe` (Electron shell)
- All Chromium runtime files

> **Note:** The `electron-builder` configuration is in `electron-app/package.json` under the `"build"` key.

---

## Step 6 — Create the Installer (Inno Setup)

### Prerequisites
- ✅ Backend built (Step 2) — `backend-windows/dist/enterprise_monitor_backend/` exists
- ✅ Electron packaged (Step 5) — `electron-app/release/win-unpacked/` exists
- ✅ Icon file exists — `electron-app/resources/icon.ico`

### Compile the installer

1. Open **Inno Setup Compiler**
2. Open `installer.iss` from the project root
3. Click **Build → Compile** (or press `Ctrl+F9`)
4. The installer is created at: `installer/Enterprise_Monitor_Setup.exe`

### What the installer does

1. Copies Electron app to `C:\Program Files\Enterprise Monitor\`
2. Copies backend to `C:\ProgramData\EnterpriseMonitor\backend\`
3. Locks backend directory (SYSTEM + Administrators ACL)
4. Registers `EnterpriseMonitorBackend` scheduled task (ONLOGON, HIGHEST privilege)
5. Starts the backend immediately
6. Launches the Electron GUI

---

## Step 7 — Post-Install Verification

```powershell
# 1. Check the backend is running
tasklist | findstr enterprise_monitor_backend

# 2. Check the scheduled task
schtasks /query /tn "EnterpriseMonitorBackend" /fo LIST

# 3. Check the API health
curl http://127.0.0.1:51235/health

# 4. Check the backend log
type "%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log"
```

---

## Complete Build Commands (Summary)

```powershell
# ── 1. Backend ─────────────────────────────
cd backend-windows
pip install -r requirements.txt
python -m PyInstaller enterprise_monitor_backend.spec

# ── 2. Electron ────────────────────────────
cd ../electron-app
npm install
npm run dist:dir

# ── 3. Installer ───────────────────────────
# Open installer.iss in Inno Setup → Compile
# Output: installer/Enterprise_Monitor_Setup.exe
```

---

## File Locations After Installation

| Path | Contents |
|---|---|
| `C:\Program Files\Enterprise Monitor\` | Electron app + Chromium runtime |
| `C:\ProgramData\EnterpriseMonitor\backend\` | Python backend (EXE + DLLs) — ACL locked |
| `%LOCALAPPDATA%\EnterpriseMonitor\` | Database, config, logs, screenshots, videos |
| `%LOCALAPPDATA%\EnterpriseMonitor\monitoring.db` | SQLite database (WAL mode) |
| `%LOCALAPPDATA%\EnterpriseMonitor\config.json` | Server endpoints + API keys |
| `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log` | Application log |

---

## Uninstalling

Run the uninstaller from **Settings → Apps → Enterprise Monitor → Uninstall**, or from the Start Menu.

The uninstaller:
1. Kills the Electron GUI and backend process
2. Removes the scheduled task
3. Resets ACLs on locked directories
4. Deletes all installed files and data
