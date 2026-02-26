<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" />
  <img src="https://img.shields.io/badge/Backend-Python%20%7C%20FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Frontend-Electron-47848F?style=for-the-badge&logo=electron&logoColor=white" />
  <img src="https://img.shields.io/badge/Database-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/Version-1.0.0-green?style=for-the-badge" />
</p>

# 🖥️ Enterprise Monitor

**A production-grade, enterprise-level employee activity monitoring system for Windows** — built with a **Master/Child process architecture** that pairs an **Electron desktop UI** with a **Python FastAPI backend**, all packaged into a single-click NSIS installer via `electron-builder`.

This project demonstrates deep expertise in **systems programming**, **desktop application architecture**, **real-time monitoring**, **secure authentication**, **multi-threaded data pipelines**, and **enterprise deployment** (Registry auto-start, graceful shutdown, NSIS cleanup hooks).

---

## 🖼️ Screenshots

### Login Page
> Gradient background with animated floating circles, credential-protected access, and a forgot password flow via security Q&A.

<p align="center">
  <img src="resources/Login_page.png" alt="Login Page" width="700" />
</p>

### Admin Dashboard
> Real-time statistics with Chart.js visualizations — active hours, apps tracked, screenshots, clipboard events. Timezone-aware display with selector.

<p align="center">
  <img src="resources/Dashboard.png" alt="Dashboard Overview" width="700" />
</p>

<p align="center">
  <img src="resources/Dashboard2.png" alt="Dashboard Charts" width="700" />
</p>

### Monitoring Data
> Tabbed interface for App Activity, Browser logs, Clipboard events, Keystrokes, and Screen Recordings.

<p align="center">
  <img src="resources/Monitor data app.png" alt="Monitor Data - Apps" width="700" />
</p>

<p align="center">
  <img src="resources/monitor data video4.png" alt="Monitor Data - Videos" width="700" />
</p>

### Server & API Configuration
> 6 configurable ERP endpoint URLs with live payload preview and API key setup.

<p align="center">
  <img src="resources/apiconfig.png" alt="API Configuration" width="700" />
</p>

### Credential Management
> Username/password change with mandatory security Q&A setup for password recovery.

<p align="center">
  <img src="resources/change credeintial.png" alt="Credential Management" width="700" />
</p>

---

## 📋 Table of Contents

- [Architecture Overview](#-architecture-overview)
- [Feature Highlights](#-feature-highlights)
- [Technology Stack](#-technology-stack)
- [Security Design](#-security-design)
- [Project Structure](#-project-structure)
- [Monitoring Capabilities](#-monitoring-capabilities)
- [ERP Sync Engine](#-erp-sync-engine)
- [Installation & Development](#-installation--development)
- [Build & Distribution](#-build--distribution)

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     ELECTRON (Master Process)                    │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────────────┐  │
│  │  Tray    │   │  BrowserWindow│   │  Preload (Context Bridge)│  │
│  │  Manager │   │  (Renderer)   │   │  • Secure IPC Bridge     │  │
│  └──────────┘   └──────┬───────┘   └──────────────────────────┘  │
│                        │ IPC Handlers                            │
│  ┌─────────────────────┴───────────────────────────────────────┐  │
│  │ Main Process: spawn → port.info handshake → ApiClient       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│          │ HTTP (dynamic port)                                    │
└──────────┼──────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│              PYTHON BACKEND (Child Process)                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  FastAPI + Uvicorn (dynamic port, 127.0.0.1 only)           ││
│  │  • JWT Auth  • REST API  • CORS  • Lifecycle Hooks          ││
│  │  • Graceful Shutdown Endpoint (/api/shutdown)                ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │Screenshot│ │App       │ │Browser   │ │Keylogger           │  │
│  │Monitor   │ │Tracker   │ │Tracker   │ │(pynput)            │  │
│  └──────────┘ └──────────┘ │(UIAuto)  │ └────────────────────┘  │
│  ┌──────────┐ ┌──────────┐ └──────────┘ ┌────────────────────┐  │
│  │Clipboard │ │Screen    │ ┌──────────┐ │Data Cleanup Service│  │
│  │Monitor   │ │Recorder  │ │Sync      │ │(7-day retention)   │  │
│  │          │ │(OpenCV)  │ │Service   │ └────────────────────┘  │
│  └──────────┘ └──────────┘ │(6-type)  │                         │
│                             └──────────┘                         │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  SQLite (WAL mode, shared connection, thread-safe Lock)     ││
│  │  • screenshots • app_activity • browser_activity            ││
│  │  • clipboard_events • text_logs • video_recordings          ││
│  │  • device_config                                            ││
│  └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Master/Child Process Model

| Aspect | Electron (Master) | Python Backend (Child) |
|---|---|---|
| **Lifecycle** | Spawns backend, owns shutdown | Dies with master |
| **Port** | Polls `port.info` | Writes atomically (tmp → rename) |
| **Communication** | HTTP via `ApiClient` | FastAPI REST API |
| **Startup Guard** | Deletes stale `port.info` | Named Windows Mutex (single-instance) |
| **Shutdown** | Graceful HTTP → force-kill fallback | `/api/shutdown` → stops all services |
| **Auto-start** | Registry `Run` key (like Slack, Teams) | Spawned by Electron on startup |

---

## ✨ Feature Highlights

| Category | Feature | Technical Detail |
|---|---|---|
| 🖥️ **App Tracking** | Active window monitoring | `win32gui` + `psutil` — app name, window title, duration |
| 🌐 **Browser Tracking** | URL capture from 14+ browsers | `uiautomation` COM API — Chromium Omnibox + Gecko fallback |
| 📸 **Screenshots** | Periodic screen capture | `mss` library — multi-monitor aware |
| 🎥 **Screen Recording** | Continuous MP4 recording | `OpenCV` + `mss` — configurable chunk duration |
| ⌨️ **Keystroke Logging** | Application-aware text capture | `pynput` — captures per-app-context |
| 📋 **Clipboard Monitoring** | Copy event tracking | `pyperclip` — content type + preview |
| 🔄 **ERP Sync** | 6-type data sync engine | JSON POST + multipart file upload to configurable endpoints |
| 🔐 **Authentication** | JWT + bcrypt + security Q&A | Token expiry, credential update, password reset flow |
| 🖥️ **System Tray** | Background operation | Minimize to tray, credential-protected quit |
| 📊 **Dashboard** | Real-time analytics | Chart.js visualizations, timezone-aware display |
| 🛡️ **Anti-Tamper** | Credential-gated exit | Users cannot quit without admin password |
| 📦 **Installer** | One-click deployment | electron-builder NSIS with custom cleanup hooks |

---

## 🛠️ Technology Stack

### Backend (Python)
| Component | Technology | Purpose |
|---|---|---|
| Web Framework | **FastAPI** + **Uvicorn** | Async REST API with auto-docs |
| Database | **SQLite** (WAL mode) | Thread-safe with shared connection + Lock |
| Auth | **python-jose** (JWT) + **passlib** (bcrypt) | Stateless auth with password hashing |
| Screenshot | **mss** + **Pillow** | Cross-monitor screen capture |
| Recording | **OpenCV** (`cv2`) + **mss** + **NumPy** | MP4 video encoding |
| Browser | **uiautomation** + **comtypes** | Windows UI Automation COM API |
| Keylogger | **pynput** | OS-level keyboard hook |
| System APIs | **pywin32** (`win32gui`, `win32process`) | Window detection, process info |
| HTTP Sync | **requests** | ERP endpoint integration |
| Build | **PyInstaller** (onedir) | Single-folder executable distribution |

### Frontend (Electron + TypeScript)
| Component | Technology | Purpose |
|---|---|---|
| Framework | **Electron** (contextIsolation) | Secure desktop shell |
| IPC | **ipcMain** / **ipcRenderer** | Type-safe preload bridge |
| State | **electron-store** | Persistent token/config storage |
| Charting | **Chart.js** (CDN) | Dashboard visualizations |
| Build | **electron-builder** (NSIS) | Windows installer with custom uninstall hooks |

### Deployment & Process Lifecycle
| Component | Technology | Purpose |
|---|---|---|
| Installer | **electron-builder** (NSIS) | Professional Windows installer/uninstaller |
| Auto-start | **Windows Registry** (`Run` key) | Industry-standard auto-launch (like Slack, Teams) |
| Graceful Shutdown | **HTTP endpoint** (`/api/shutdown`) | Clean service stop before process exit |
| Zombie Prevention | **Custom NSIS hooks** (`installer.nsh`) | Kills backend + cleans data on uninstall |
| Single Instance | **Named Windows Mutex** | Prevents duplicate backend processes |

---

## 🔐 Security Design

```
Authentication Flow
──────────────────
POST /api/auth/login  ─── bcrypt verify ──→  JWT token (5-min expiry)
                                              │
Bearer token ──→ verify_token() ──→ Protected endpoints
                                              │
Forgot Password ──→ Security Q&A verify ──→ Password reset

Process Lifecycle
─────────────────
Login → Auto-start on login via Registry Run key
      → Electron spawns backend (child_process.spawn)
      → Backend writes port.info atomically
      → Electron polls, connects via dynamic port

Quit  → Credential-gated (anti-tamper)
      → POST /api/shutdown (graceful stop)
      → Force-kill fallback after 3s timeout

Uninstall → NSIS hooks kill processes
          → Registry auto-start entry removed
          → %LOCALAPPDATA%\EnterpriseMonitor cleaned up

File System Security
────────────────────
%LOCALAPPDATA%\EnterpriseMonitor\
  ├── monitoring.db      ← SQLite (WAL mode)
  ├── config.json        ← Server endpoints + API keys
  ├── users.json         ← bcrypt-hashed credentials
  ├── security_qa.json   ← Hashed security answers
  ├── logs/backend.log   ← Application logs
  └── port.info          ← Dynamic port (ephemeral)
```

**Key Security Features:**
- **bcrypt** password hashing (not SHA — resistant to GPU attacks)
- **JWT** with short expiry (5 minutes) — stateless, no session DB needed
- **Context Isolation** in Electron — no `nodeIntegration`, secure preload bridge
- **Named Windows Mutex** — prevents duplicate backend processes
- **Credential-protected quit** — prevents unauthorized app termination
- **Atomic port handshake** — prevents race conditions on startup
- **Graceful shutdown** — HTTP-first → force-kill fallback (no zombie processes)

---

## 📁 Project Structure

```
enterprise-monitor-complete/
├── backend-windows/                    # Python Backend
│   ├── main.py                         # Entry point — port handshake, mutex guard
│   ├── api_server.py                   # FastAPI app — 30+ REST endpoints
│   ├── auth/
│   │   └── auth_manager.py             # JWT, bcrypt, security Q&A
│   ├── database/
│   │   └── db_manager.py               # SQLite — WAL mode, thread-safe Lock
│   ├── monitoring/
│   │   ├── app_tracker.py              # Active window monitoring
│   │   ├── browser_tracker.py          # URL capture (14+ browsers)
│   │   ├── screenshot.py               # Periodic screen capture
│   │   ├── screen_recorder.py          # MP4 recording (OpenCV)
│   │   ├── clipboard.py                # Clipboard monitoring
│   │   ├── keylogger.py                # Keystroke capture (pynput)
│   │   └── data_cleaner.py             # 7-day data retention
│   ├── services/
│   │   └── sync_service.py             # 6-type ERP sync engine
│   ├── utils/
│   │   └── config_manager.py           # JSON config persistence
│   ├── requirements.txt                # Python dependencies
│   └── enterprise_monitor_backend.spec # PyInstaller build spec
│
├── electron-app/                       # Electron Frontend
│   ├── src/
│   │   ├── main/
│   │   │   ├── main.ts                 # Master process — spawn, port handshake
│   │   │   ├── api-client.ts           # HTTP client wrapper
│   │   │   └── tray.ts                 # System tray management
│   │   ├── preload/
│   │   │   └── preload.ts              # Context Bridge (secure IPC)
│   │   └── renderer/
│   │       ├── index.html              # Dashboard UI (2000+ lines)
│   │       └── renderer.js             # Dashboard logic (1200+ lines)
│   ├── build/
│   │   └── installer.nsh               # Custom NSIS uninstall hooks
│   ├── package.json
│   └── tsconfig.json
│
├── resources/                          # App icons + screenshots
│   ├── Login_page.png
│   ├── Dashboard.png
│   ├── Dashboard2.png
│   ├── Monitor data app.png
│   ├── monitor data video4.png
│   ├── apiconfig.png
│   ├── change credeintial.png
│   ├── icon.ico / icon.icns
│   └── icon-source.png
│
├── scripts/
│   └── setup-windows.bat               # Backend builder (PyInstaller + deploy)
│
└── README.md                           # This file
```

---

## 🔍 Monitoring Capabilities

### Browser Tracker — 14+ Browser Support

The `BrowserTracker` uses Windows UI Automation to read the address bar directly — **no browser extensions required**. It supports:

| Engine | Browsers |
|---|---|
| **Chromium** | Chrome, Edge, Brave, Opera, Opera GX, Vivaldi, Yandex, DuckDuckGo, UC Browser, Cent, 360 Browser |
| **Gecko** | Firefox, Waterfox, LibreWolf, Thunderbird |

**Detection Strategy (Chromium):**
1. `AutomationId="omnibox"` — most reliable across all builds
2. `Name="Address and search bar"` — Edge + some Chrome versions
3. Structural deep walk — recursive UIA tree search (fallback)

**Detection Strategy (Gecko/Firefox):**
1. ToolbarControl walk — Firefox v110+
2. Named toolbar lookup — locale-dependent variants
3. ComboBoxControl — Firefox < v110 legacy

### Thread-Safe Database

All monitoring threads share a **single persistent SQLite connection** with:
- **WAL journal mode** — readers never block writers
- **threading.Lock()** — serializes all cursor operations
- **`check_same_thread=False`** — safe with our explicit locking

---

## 🔄 ERP Sync Engine

The `SyncService` synchronizes 6 data types to configurable ERP endpoints:

| # | Data Type | Transport | Endpoint Config Key |
|---|---|---|---|
| 1 | App Activity | JSON POST | `url_app_activity` |
| 2 | Browser Activity | JSON POST | `url_browser` |
| 3 | Clipboard Events | JSON POST | `url_clipboard` |
| 4 | Keystroke Logs | JSON POST | `url_keystrokes` |
| 5 | Screenshots | Multipart POST | `url_screenshots` |
| 6 | Video Recordings | Multipart POST | `url_videos` |

**Features:**
- Per-record sync with tracked `synced`/`is_synced` flags
- Configurable sync interval (default: 300s)
- `X-API-Key` header authentication
- UTC-normalized timestamps for ERP compatibility
- Automatic retry on next cycle for failed records
- Manual sync trigger via dashboard button

---

## 🚀 Installation & Development

### Prerequisites

- **Python 3.10+** (with `pip`)
- **Node.js 18+** (with `npm`)
- **Windows 10/11** (required for `uiautomation`, `pywin32`)

### Quick Start (Development)

```bash
# 1. Install Python dependencies
cd backend-windows
pip install -r requirements.txt

# 2. Install Electron dependencies
cd ../electron-app
npm install

# 3. Start the app (Electron spawns backend automatically)
npm start
```

> **Default credentials:** `admin` / `admin` — you'll be prompted to change on first login.

---

## 📦 Build & Distribution

### Step 1: Build the Python Backend

```bash
cd backend-windows
python -m PyInstaller enterprise_monitor_backend.spec
```

This produces `dist/enterprise_monitor_backend/` — a folder containing the EXE and all dependencies.

### Step 2: Build the Electron Installer

```bash
cd electron-app
npm run dist
```

This packages everything into a Windows NSIS installer at `electron-app/release/`. The backend is automatically bundled from `backend-windows/dist/` via the `extraResources` config in `package.json`.

> ⚠️ **Important:** Always build the backend **first** — `npm run dist` copies from `backend-windows/dist/`, so that folder must exist and be up-to-date.

### What the Installer Handles

| Phase | Action |
|---|---|
| **Install** | Kills any old backend → deploys app + backend |
| **Auto-start** | Electron registers in Windows Registry `Run` key |
| **Uninstall** | Kills backend + Electron → removes registry entry → deletes `%LOCALAPPDATA%\EnterpriseMonitor` |

---

## 👨‍💻 Author

**Ashraful Anik**

Built as a demonstration of full-stack desktop application engineering — from low-level Windows COM APIs to high-level Electron UI, with production-grade security, deployment, and maintainability throughout.

---

<p align="center">
  <sub>Enterprise Monitor v1.0.0 — Windows Desktop Application</sub>
</p>
