# Enterprise Monitor

**Professional Employee Monitoring System for Windows**

A comprehensive, production-ready monitoring solution built with Electron, Python FastAPI, and modern web technologies. Designed for enterprise environments to track employee productivity, application usage, browser history, keystrokes, screenshots, clipboard activity, and screen recordings — all synchronized to your ERP server over HTTPS.

| Capability | Details |
|---|---|
| 📸 Screenshot Capture | Every 5 s, auto-compressed to 60–80 KB |
| 🖥️ App Tracking | Active process + window title every 5 s |
| 🌐 Browser URL Tracking | UI Automation — no proxy, no extension needed |
| ⌨️ Keystroke Logging | Buffered per-window, privacy filter on login screens |
| 📹 Screen Recording | 720p MP4 in 5-min chunks (admin-controlled, off by default) |
| 📋 Clipboard Monitoring | Real-time content-type + 100-char preview |
| 🔄 6-Type ERP Sync | Per-endpoint URLs, batched uploads, automatic retry |
| 🖥️ Admin Dashboard | Electron GUI — charts, logs, screenshot gallery, config modal |
| 🔒 JWT Auth | 30-minute tokens, enforced password strength policy |

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Technology Stack](#-technology-stack)
- [Key Features](#-key-features)
- [Data Flow & Storage](#-data-flow--storage)
- [Quick Start (Development)](#-quick-start-development)
- [Production Deployment](#-production-deployment)
- [Building the Electron Installer](#-building-the-electron-installer)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [Configuration Reference](#-configuration-reference)
- [Security & Privacy](#-security--privacy)
- [Troubleshooting](#-troubleshooting)
- [Important Notes](#-important-notes)
- [Support & Logs](#-support--logs)

---

## 🎯 Overview

Enterprise Monitor is a **Windows-focused** employee monitoring system. The backend is a Python FastAPI service that runs as a Windows service; the front-end is an Electron app that connects to it over HTTP on localhost.

### Platform Support

| Platform | Status | Path |
|---|---|---|
| **Windows 10/11** | ✅ Fully supported | `backend-windows/` |
| **macOS 13+** | 🔶 Experimental | `backend-macos/` |

---

## 🏗️ Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                       ELECTRON APP (GUI)                       │
│  ┌───────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │  Main Process │  │    Renderer      │  │  System Tray   │  │
│  │  (Node.js)    │  │  (HTML/CSS/JS)   │  │   Manager      │  │
│  └───────┬───────┘  └────────┬─────────┘  └───────┬────────┘  │
│          └───────────────────┴───────────────────┘             │
│                              │  IPC (contextBridge)            │
└──────────────────────────────┼─────────────────────────────────┘
                               │
                 HTTP REST API — http://127.0.0.1:51235
                               │
┌──────────────────────────────┼─────────────────────────────────┐
│               PYTHON BACKEND (FastAPI + Uvicorn)               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  api_server.py  •  JWT Auth  •  CORS  •  Pydantic models │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────── MONITORING SERVICES ─────────────────┐  │
│  │  Screenshot (5 s)    App Tracker (5 s)                   │  │
│  │  Browser Tracker (5 s, UI Automation COM)                │  │
│  │  Keylogger (pynput)  Clipboard (real-time)               │  │
│  │  Screen Recorder (admin-toggled, 720p MP4)               │  │
│  │  Data Cleaner (24 h) Sync Service v2 (300 s, 6 types)   │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────── SQLite DATABASE ─────────────────────┐  │
│  │  screenshots  app_activity  clipboard_events             │  │
│  │  browser_activity  text_logs  video_recordings           │  │
│  │  device_config  (identity KV store)                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
              HTTPS POST every 300 s — 6 separate endpoints
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│        ERP SERVER (External) — 6 configurable endpoints        │
│  url_app_activity  → POST JSON   (app usage sessions)          │
│  url_browser       → POST JSON   (browser URL visits)          │
│  url_clipboard     → POST JSON   (clipboard events)            │
│  url_keystrokes    → POST JSON   (keystroke / text logs)       │
│  url_screenshots   → POST multipart (PNG files + metadata)     │
│  url_videos        → POST multipart (MP4 chunks + metadata)    │
└────────────────────────────────────────────────────────────────┘
```

### How the Components Fit Together

1. **Electron app** is the admin console. It launches hidden in the system tray, connects to the Python backend over HTTP, and renders the dashboard in a `BrowserWindow`.
2. **Python backend** (FastAPI on port `51235`) owns all monitoring logic. It writes to SQLite, syncs to ERP, and exposes a JWT-authenticated REST API.
3. **In production**, the Python backend is compiled to a single `.exe` via PyInstaller and installed as a **Windows service** via NSSM — auto-starting at boot, no user session required.

---

## 🛠️ Technology Stack

### Electron App

| Technology | Version | Purpose |
|---|---|---|
| **Electron** | 40.x | Desktop shell |
| **TypeScript** | 5.3.x | Type-safe JavaScript |
| **Chart.js** | CDN latest | Activity charts |
| **Axios** | 1.6.x | HTTP calls to backend |
| **electron-store** | 8.1.x | Persistent local settings |
| **electron-builder** | 26.x | NSIS installer packaging |

### Python Backend

| Package | Purpose |
|---|---|
| **FastAPI** | Async REST framework |
| **Uvicorn** | ASGI server (localhost only) |
| **SQLite 3** | Embedded data store |
| **python-jose** | JWT HS256 tokens |
| **passlib** | Password utility library |
| **mss** | Screen capture (screenshots + video frames) |
| **Pillow** | JPEG compression for screenshots |
| **opencv-python** | MP4 encoding (mp4v / XVID codec) |
| **numpy** | Frame array manipulation for video |
| **pywin32** | `win32gui` / `win32process` — foreground window info |
| **psutil** | Process name lookup from PID |
| **uiautomation** | Read browser address bar via Windows COM |
| **pynput** | OS keyboard event hook for keystroke logging |
| **pyperclip** | Clipboard read helper |
| **requests** | HTTPS sync to ERP endpoints |
| **tzdata** | IANA timezone database (Windows lacks built-in) |

### Installer / DevOps

| Tool | Purpose |
|---|---|
| **PyInstaller** | Package Python backend → single `.exe` |
| **NSSM** (bundled in `resources/`) | Register `.exe` as a Windows service |
| **icacls** | Lock log/video dirs from standard users |

---

## ✨ Key Features

### 1. Screenshot Monitoring

- **Interval**: every 5 s (configurable via `interval_seconds` in `screenshot.py`)
- **Compression**: JPEG, target 60–80 KB per image
- **Storage**: `%LOCALAPPDATA%\EnterpriseMonitor\screenshots\`
- **Metadata**: `timestamp`, `file_path`, `active_window`, `active_app`, `username`
- **Sync**: multipart upload to `url_screenshots` endpoint

### 2. Application Tracking

- **Interval**: every 5 s
- **Method**: `win32gui.GetForegroundWindow()` → PID → `psutil.Process(pid).name()`
- **Data**: process name, window title, duration in seconds, username, timestamp
- **Sync**: JSON POST to `url_app_activity`

### 3. Browser URL Tracking

- **Method**: Windows UI Automation COM API reads the active browser's address bar control directly. No extension, proxy, or certificate is required.
- **Supported browsers**:

  | Browser | Process |
  |---|---|
  | Chrome | `chrome.exe` |
  | Edge | `msedge.exe` |
  | Firefox | `firefox.exe` |
  | Brave | `brave.exe` |
  | Opera | `opera.exe` |
  | Opera GX | `operagx.exe` |
  | Yandex Browser | `browser.exe` |
  | DuckDuckGo | `duckduckgo.exe` |
  | UC Browser | `ucbrowser.exe` |
  | Vivaldi | `vivaldi.exe` |
  | Cent Browser | `cent.exe` |
  | 360 Browser | `360chrome.exe` |
  | Waterfox | `waterfox.exe` |
  | LibreWolf | `librewolf.exe` |
  | Thunderbird | `thunderbird.exe` *(email client — tracked via its address bar)* |

- **Data**: `browser_name`, `url`, `page_title`, `username`, `timestamp`
- **Sync**: JSON POST to `url_browser`

### 4. Keystroke / Text Logging

- **Library**: `pynput.keyboard.Listener` — OS-level event hook, non-suppressing
- **Buffering**: keystrokes are buffered per active window; flushed on `Enter` key or window switch
- **Privacy filter**: capture **suspended** when the active window title contains any of:
  `password`, `login`, `sign in`, `signin`, `credentials`
- **Data**: `application`, `window_title`, `content` (flushed buffer), `username`, `timestamp`
- **Sync**: JSON POST to `url_keystrokes`

### 5. Clipboard Monitoring

- **Trigger**: OS clipboard-change event via pyperclip polling
- **Data**: `content_type` (text/image/file), `content_preview` (first 100 chars), `username`, `timestamp`
- **Privacy**: full clipboard content is never stored
- **Sync**: JSON POST to `url_clipboard`

### 6. Screen Recording

- **Default**: **OFF** — must be enabled explicitly by an admin
- **Toggle**: dashboard button or `POST /api/monitoring/video/toggle`
- **Format**: MP4 (mp4v / XVID codec via OpenCV)
- **Resolution**: 1280 × 720 at 10 FPS
- **Rotation**: new file every 5 minutes
- **Storage**: `C:\ProgramData\EnterpriseMonitor\videos\` (restricted ACLs)
- **Metadata**: `timestamp`, `file_path`, `duration_seconds` in `video_recordings` table
- **Sync**: multipart upload to `url_videos` (3 files per cycle)

### 7. ERP Synchronization — v2 (6 Types)

| Config Key | Method | Content-Type | Batch Size |
|---|---|---|---|
| `url_app_activity` | POST | `application/json` | 50 records |
| `url_browser` | POST | `application/json` | 50 records |
| `url_clipboard` | POST | `application/json` | 50 records |
| `url_keystrokes` | POST | `application/json` | 50 records |
| `url_screenshots` | POST | `multipart/form-data` | 10 files |
| `url_videos` | POST | `multipart/form-data` | 3 files |

- **Interval**: every 300 s (configurable)
- **Auth header**: `X-API-Key: <api_key>` (when configured)
- **Retry**: failed records stay `synced = 0` and are retried next cycle
- **Missing files**: marked synced immediately to avoid infinite retry after cleanup

#### Payload Examples

**app_activity**
```json
{
  "pcName":       "DESKTOP-ABC123",
  "appName":      "chrome.exe",
  "windowsTitle": "GitHub - Google Chrome",
  "startTime":    "2026-02-17T12:00:00+00:00",
  "endTime":      "2026-02-17T12:00:05+00:00",
  "duration":     5,
  "syncTime":     "2026-02-17T12:05:00+00:00"
}
```

**browser**
```json
{
  "pcName":      "DESKTOP-ABC123",
  "browserName": "Chrome",
  "url":         "https://github.com",
  "pageTitle":   "GitHub",
  "timestamp":   "2026-02-17T12:00:00+00:00",
  "syncTime":    "2026-02-17T12:05:00+00:00"
}
```

**clipboard**
```json
{
  "pcName":         "DESKTOP-ABC123",
  "contentType":    "text",
  "contentPreview": "https://example.com/link",
  "timestamp":      "2026-02-17T12:00:00+00:00",
  "syncTime":       "2026-02-17T12:05:00+00:00"
}
```

**keystrokes**
```json
{
  "pcName":      "DESKTOP-ABC123",
  "application": "WINWORD.EXE",
  "windowTitle": "Document1 - Microsoft Word",
  "content":     "quarterly sales report draft",
  "timestamp":   "2026-02-17T12:00:00+00:00",
  "syncTime":    "2026-02-17T12:05:00+00:00"
}
```

**screenshots / videos** — multipart/form-data with metadata fields + binary file.

### 8. Automated Data Cleanup

- **Runs**: once at startup, then every 24 hours
- **Retention**: 7 days (configurable via `retention_days`)
- **Scope**: all five tracking tables + screenshot files on disk

### 9. Admin Dashboard

- **Default credentials**: `admin` / `Admin@123` (⚠️ change immediately)
- **Password policy**: 8–16 characters, uppercase + lowercase + special symbol required
- **Sections**: Overview · Timeline · App Usage · App Logs · Browser Logs · Keystroke Logs · Clipboard Logs · Screenshots · Recordings · Config API

### 10. Identity Management

Override the raw hostname sent in sync payloads:

```json
POST /api/config/identity
{"device_alias": "Finance-PC-01", "user_alias": "Jane Smith"}
```

### 11. System Tray Integration

- Starts **hidden** — only tray icon visible
- Registers as a Windows **login item** (auto-launches on user login)
- Closing the dashboard **hides** it; only "Quit" in tray exits

---

## 💾 Data Flow & Storage

### File System Layout

```
%LOCALAPPDATA%\EnterpriseMonitor\
├── monitoring.db          ← SQLite database (7 tables)
├── config.json            ← Runtime configuration
├── users.json             ← Admin credentials  ⚠️ plain text — protect this file
├── security_qa.json       ← Security Q&A pairs (answers stored lowercase)
├── logs\
│   ├── backend.log              ← Main application log
│   ├── backend_stdout.log       ← NSSM service stdout
│   └── backend_stderr.log       ← NSSM service stderr
└── screenshots\
    ├── screenshot_20260217_120000.jpg
    └── ...

C:\ProgramData\EnterpriseMonitor\
├── backend\
│   └── enterprise_monitor_backend.exe   ← PyInstaller binary
└── videos\
    ├── recording_20260217_120000.mp4    ← 5-minute chunk
    └── ...
```

### Database Schema (`monitoring.db`)

> All five tracking tables include `username TEXT DEFAULT ''` and `synced INTEGER DEFAULT 0`.

**`screenshots`**

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | ISO-8601 UTC |
| file_path | TEXT | Absolute path |
| active_window | TEXT | Window title at capture |
| active_app | TEXT | Executable name |
| username | TEXT | OS username |
| created_at | TEXT | |
| synced | INTEGER | 0 = pending, 1 = done |

**`app_activity`**

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | |
| app_name | TEXT | e.g. `chrome.exe` |
| window_title | TEXT | |
| duration_seconds | INTEGER | |
| username | TEXT | |
| created_at | TEXT | |
| synced | INTEGER | |

**`clipboard_events`**

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | |
| content_type | TEXT | `text` / `image` / `file` |
| content_preview | TEXT | Max 100 chars |
| username | TEXT | |
| created_at | TEXT | |
| synced | INTEGER | |

**`browser_activity`** *(added via migration)*

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | |
| browser_name | TEXT | e.g. `Chrome` |
| url | TEXT | Full URL |
| page_title | TEXT | |
| username | TEXT | |
| created_at | TEXT | |
| synced | INTEGER | added via migration |

**`text_logs`** *(added via migration)*

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | |
| application | TEXT | Executable name |
| window_title | TEXT | |
| content | TEXT | Flushed keystroke buffer |
| username | TEXT | |
| created_at | TEXT | |
| synced | INTEGER | added via migration |

**`video_recordings`**

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT | Recording start |
| file_path | TEXT | Absolute path |
| duration_seconds | INTEGER | |
| is_synced | INTEGER | 0 = pending, 1 = done |
| created_at | TEXT | |

**`device_config`** (KV store)

| Column | Type | Notes |
|---|---|---|
| key | TEXT PK | `device_alias` or `user_alias` |
| value | TEXT | |

### Configuration File (`config.json`)

```json
{
  "api_key":               "",
  "sync_interval_seconds": 300,
  "url_app_activity":      "",
  "url_browser":           "",
  "url_clipboard":         "",
  "url_keystrokes":        "",
  "url_screenshots":       "",
  "url_videos":            "",
  "server_url":            "",
  "recording_enabled":     false,
  "timezone":              "UTC",
  "device_id":             "auto-generated-uuid"
}
```

> `server_url` and `device_id` are kept for backward compatibility with v1 installs.

---

## 🚀 Quick Start (Development)

### Prerequisites

- Windows 10/11
- Python 3.11+ — [python.org](https://www.python.org/downloads/)
- Node.js 18+ — [nodejs.org](https://nodejs.org/)
- Visual C++ Redistributable 2015–2022 — [Download](https://aka.ms/vs/17/release/vc_redist.x64.exe) *(required by `uiautomation`)*

### Step 1 — Start the Python Backend

```cmd
cd backend-windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Backend binds to **`http://127.0.0.1:51235`** (localhost only — not accessible over the network).

### Step 2 — Start the Electron Dashboard

```cmd
cd electron-app
npm install
npm run build
npm start
```

### Step 3 — Log In

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `Admin@123` |

> ⚠️ **Change this password immediately** via Settings → Change Credentials.

### Step 4 — Configure ERP Endpoints

Click **"Config Server API"** in the dashboard and enter your per-type endpoint URLs and API key.

---

## 🏭 Production Deployment

For production the backend runs as a **Windows service** (auto-start at boot, no active user session required). The `scripts\setup-windows.bat` script automates the full install.

### Requirements

- Run as **Administrator**
- Python 3.11+ in PATH with `pip install pyinstaller` done once
- `resources\nssm.exe` present (already bundled in the repo)

### Run the Installer

```cmd
REM Right-click → Run as Administrator
scripts\setup-windows.bat
```

### What the Script Does (7 Steps)

| Step | Action |
|---|---|
| 1 | Verify Python, PyInstaller, nssm.exe are available |
| 2 | Create `C:\ProgramData\EnterpriseMonitor\{backend,logs,videos}` + apply ACLs |
| 3 | Build `enterprise_monitor_backend.exe` via PyInstaller (`--onefile --noconsole`) |
| 4 | Copy `.exe` to `C:\ProgramData\EnterpriseMonitor\backend\` |
| 5 | Remove existing `EnterpriseMonitorBackend` service (if any) |
| 6 | Install + configure the service via NSSM (auto-start, 5 MB log rotation) |
| 7 | Start the service |

> PyInstaller build time is approximately 3–8 minutes on first run.

### ACL Security Applied by the Installer

| Directory | Admins / SYSTEM | Standard Users |
|---|---|---|
| `C:\ProgramData\EnterpriseMonitor\` | Full Control | No list / no read |
| `.\logs\` | Full Control | **Denied** read + execute |
| `.\videos\` | Full Control | **Denied** read + execute |

Standard users cannot discover log files or view their own recordings.

### Service Management Commands

```cmd
nssm start   EnterpriseMonitorBackend
nssm stop    EnterpriseMonitorBackend
nssm restart EnterpriseMonitorBackend
nssm status  EnterpriseMonitorBackend
nssm remove  EnterpriseMonitorBackend confirm
```

---

## 📦 Building the Electron Installer

```cmd
cd electron-app
npm install
npm run dist
```

Produces a NSIS installer at `electron-app\release\Enterprise Monitor Setup x.x.x.exe`.

| Script | Output |
|---|---|
| `npm start` | Build TypeScript + launch dev mode |
| `npm run build` | TypeScript → JS only |
| `npm run dist` | Full NSIS installer (`.exe`) |
| `npm run dist:dir` | Unpacked directory (no installer) |
| `npm run pack` | Unpacked dir (fast test build) |

**Installer settings** (from `package.json`):
- App ID: `com.ashraful.enterprise-monitor`
- Elevation: `requireAdministrator`
- Shortcuts: Desktop + Start Menu
- Architecture: x64 only

---

## 📁 Project Structure

```
enterprise-monitor-complete/
│
├── electron-app/
│   ├── src/
│   │   ├── main/
│   │   │   ├── main.ts           # App lifecycle, IPC, login-item, tray
│   │   │   ├── api-client.ts     # Axios wrapper for backend REST API
│   │   │   └── tray.ts           # System tray icon + context menu
│   │   ├── preload/
│   │   │   └── preload.ts        # contextBridge — safe IPC surface
│   │   └── renderer/
│   │       ├── index.html        # Full dashboard UI + Config API modal
│   │       └── renderer.js       # Chart.js, log tables, API calls, date picker
│   ├── resources/
│   │   ├── icon.ico / icon.png / icon.icns
│   │   └── nssm.exe              # Bundled for installer extraResources
│   ├── package.json              # Electron deps + electron-builder config
│   └── tsconfig.json
│
├── backend-windows/
│   ├── main.py                   # Uvicorn entry-point (127.0.0.1:51235)
│   ├── api_server.py             # FastAPI app, all routes, lifecycle hooks
│   ├── requirements.txt          # pip dependencies
│   ├── auth/
│   │   └── auth_manager.py       # JWT, password policy, security Q&A
│   ├── database/
│   │   └── db_manager.py         # SQLite CRUD, schema, auto-migrations
│   ├── monitoring/
│   │   ├── screenshot.py         # Periodic JPEG capture
│   │   ├── app_tracker.py        # Foreground process + window title
│   │   ├── browser_tracker.py    # UI Automation address-bar reader
│   │   ├── keylogger.py          # pynput buffered keystroke capture
│   │   ├── screen_recorder.py    # mss + OpenCV rolling MP4 recorder
│   │   ├── clipboard.py          # Clipboard change monitor
│   │   └── data_cleaner.py       # 7-day retention cleanup
│   ├── services/
│   │   └── sync_service.py       # SyncService v2 — 6-type ERP sync
│   └── utils/
│       └── config_manager.py     # JSON config read/write (get/set)
│
├── backend-macos/                # Swift/Vapor skeleton (experimental)
│   ├── Package.swift
│   └── Sources/main.swift
│
├── resources/
│   ├── icon.ico / icon.png / icon.icns
│   └── nssm.exe
│
├── scripts/
│   ├── setup-windows.bat         # 7-step production installer (run as Administrator)
│   └── setup-macos.sh            # macOS dev setup
│
├── README.md
├── IMPLEMENTATION_GUIDE.md       # Detailed deployment & troubleshooting guide
└── .gitignore
```

---

## 📡 API Reference

All endpoints except `/health` and `/` require `Authorization: Bearer <token>`.

Obtain a token: `POST /api/auth/login` → `{"success": true, "token": "..."}`

### Authentication

| Method | Path | Body / Notes |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{success, token}` |
| GET | `/api/auth/check` | Validates token → `{authenticated, username}` |
| POST | `/api/auth/change-password` | `{old_password, new_password}` |
| POST | `/api/auth/update-credentials` | `{new_username, new_password, security_q1, security_a1, security_q2, security_a2}` → `{success, force_logout}` |

> `update-credentials` changes username + password atomically and forces a re-login.

### Statistics & Charts

| Method | Path | Query Params |
|---|---|---|
| GET | `/api/statistics` | `date=YYYY-MM-DD` (optional, defaults to today) |
| GET | `/api/stats/activity` | `start=YYYY-MM-DD&end=YYYY-MM-DD` |
| GET | `/api/stats/timeline` | `date=YYYY-MM-DD` |

### Data Logs

| Method | Path | Default `limit` |
|---|---|---|
| GET | `/api/screenshots` | 20 |
| GET | `/api/data/apps` | 50 |
| GET | `/api/data/browser` | 50 |
| GET | `/api/data/keylogs` | 100 |
| GET | `/api/data/clipboard` | 50 |
| GET | `/api/data/videos` | 50 |

All log endpoints accept `limit` and `offset` query params (except `/api/data/videos` which uses `limit` only).

### Monitoring Control

| Method | Path | Notes |
|---|---|---|
| GET | `/api/monitoring/status` | `{is_monitoring, uptime_seconds}` |
| POST | `/api/monitoring/pause` | Pauses screenshot, app, browser, clipboard, keylogger |
| POST | `/api/monitoring/resume` | Resumes all five services |
| POST | `/api/monitoring/video/toggle` | Enables or disables screen recording |
| GET | `/api/monitoring/video/status` | `{recording: bool, is_active: bool}` |

### Configuration

| Method | Path | Notes |
|---|---|---|
| GET | `/api/config` | Returns all fields |
| POST | `/api/config` | Updates any subset (null = skip) |
| GET | `/api/config/identity` | `{machine_id, os_user, device_alias, user_alias}` |
| POST | `/api/config/identity` | `{device_alias?, user_alias?}` |
| GET | `/api/config/timezone` | `{timezone}` IANA string |
| POST | `/api/config/timezone` | `{timezone}` IANA string |

### Sync

| Method | Path | Notes |
|---|---|---|
| POST | `/api/sync/trigger` | Runs all 6 sync types immediately; returns per-type synced counts |

### Health

| Method | Path | Auth required |
|---|---|---|
| GET | `/health` | No |
| GET | `/` | No — returns name, version, docs_url |

**Interactive API docs**: http://localhost:51235/docs (Swagger UI) · http://localhost:51235/redoc (ReDoc)

---

## ⚙️ Configuration Reference

### Change Screenshot Interval

Edit `backend-windows/monitoring/screenshot.py`:
```python
class ScreenshotMonitor:
    def __init__(self, db_manager, interval_seconds: int = 5):
        self.interval_seconds = 60  # e.g. once per minute
```

### Change Sync Interval via API

```cmd
curl -X POST http://localhost:51235/api/config ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{"sync_interval_seconds": 600}"
```

### Configure All ERP Endpoints

```cmd
curl -X POST http://localhost:51235/api/config ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{"api_key":"YOUR_KEY","url_app_activity":"https://erp.example.com/app","url_browser":"https://erp.example.com/browser","url_clipboard":"https://erp.example.com/clipboard","url_keystrokes":"https://erp.example.com/keystrokes","url_screenshots":"https://erp.example.com/screenshots","url_videos":"https://erp.example.com/videos"}"
```

### Set Device / User Display Name

```cmd
curl -X POST http://localhost:51235/api/config/identity ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{"device_alias":"Finance-PC-01","user_alias":"Jane Smith"}"
```

### Change Display Timezone

```cmd
curl -X POST http://localhost:51235/api/config/timezone ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{"timezone":"Asia/Dhaka"}"
```

### Change Data Retention Period

Edit `backend-windows/monitoring/data_cleaner.py`:
```python
cleanup_service = CleanupService(db_manager, retention_days=14)
```

### Enable Screen Recording

```cmd
curl -X POST http://localhost:51235/api/monitoring/video/toggle ^
  -H "Authorization: Bearer YOUR_TOKEN"
REM Response: {"success": true, "recording": true}
```

---

## 🔐 Security & Privacy

### Authentication Model

| Aspect | Detail |
|---|---|
| Token format | JWT HS256 |
| Token expiry | **30 minutes** |
| Secret key | `SECRET_KEY` in `auth/auth_manager.py` — **must change before production** |
| Credentials store | `%LOCALAPPDATA%\EnterpriseMonitor\users.json` (plain-text JSON) |
| Security Q&A store | `%LOCALAPPDATA%\EnterpriseMonitor\security_qa.json` |
| Default credentials | `admin` / `Admin@123` |

### Password Policy

Enforced on every password change or credential update:

- Length: **8–16 characters**
- At least one **uppercase** letter (A–Z)
- At least one **lowercase** letter (a–z)
- At least one **special symbol**: `! @ # $ % ^ & * ( ) , . ? " : { } | < >`

### Network & Storage Security

| Measure | Detail |
|---|---|
| API binding | `127.0.0.1` only — not reachable over the network |
| ERP sync | HTTPS only |
| Log / video ACLs | `icacls` denies standard `Users` group (applied by installer) |
| Keystroke privacy filter | Capture paused on windows titled `password`, `login`, `sign in`, `signin`, `credentials` |
| Electron sandbox | `contextIsolation: true`, `nodeIntegration: false` |
| File uploads | Only sent if the matching URL is configured |

### ⚠️ Known Security Limitations

The following are **known limitations of the current implementation** that should be addressed before deploying in a production environment:

| Limitation | Risk | Recommended Fix |
|---|---|---|
| **Plain-text credentials** | `users.json` stores passwords in plain text. If this file is read (e.g., via backup, shadow copy, or privilege escalation), credentials are exposed. | Replace with bcrypt-hashed storage. The `passlib` library is already a dependency. |
| **Plain-text security Q&A** | `security_qa.json` stores answers lowercased but not hashed. | Hash answers with bcrypt before storing. |
| **Hardcoded JWT secret** | `SECRET_KEY = "your-secret-key-change-this-in-production"` is committed to source. All installations using the default share the same signing key. | Generate a unique secret per installation (e.g., in `setup-windows.bat`) and write it to a protected config file. Never commit a real secret to source control. |
| **30-minute JWT expiry** | Short expiry requires frequent re-login in the admin dashboard. There is no refresh-token mechanism in the current code. | Either add a refresh-token endpoint, or extend `ACCESS_TOKEN_EXPIRE_MINUTES` for internal deployments where long sessions are acceptable. |
| **NTFS ACLs not a complete defence** | File permissions can be bypassed by Volume Shadow Copies, backup tools, or local admin privilege escalation. | Combine ACLs with hashed credential storage (see above). |

### Legal & Privacy Compliance

> ⚠️ **You are responsible for compliance with applicable law.**

Before deploying:
- Notify employees in writing that their workstations are monitored
- Obtain consent where required (GDPR, CCPA, PDPA, etc.)
- Define a data retention and deletion policy
- Provide employees a way to access or request deletion of their data
- Assess whether keystroke logging and screen recording require additional disclosures

---

## 🔧 Troubleshooting

### Backend Won't Start

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.txt` inside the venv |
| Port 51235 in use | `netstat -ano \| findstr 51235` → `taskkill /PID <pid> /F` |
| `uiautomation` DLL error | Install Visual C++ Redistributable 2015–2022 |
| `No module named 'cv2'` | `pip install opencv-python` |
| `No module named 'win32api'` | `pip install pywin32` then `python Scripts/pywin32_postinstall.py -install` |

### Dashboard Shows "Backend Offline"

1. `curl http://localhost:51235/health`
2. Read `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log`
3. If running as service: `nssm status EnterpriseMonitorBackend`
4. Check `C:\ProgramData\EnterpriseMonitor\logs\backend_stderr.log`

### Login Fails

- Default password is `Admin@123` — capital A, `@` symbol, then `123`
- Check `%LOCALAPPDATA%\EnterpriseMonitor\users.json` for the stored value
- JWT tokens expire in **30 minutes** — log out and back in if expired

### Browser URLs Not Captured

- Install Visual C++ Redistributable 2015–2022
- Only the **foreground** (active) browser window is tracked — minimized windows are skipped
- Check `backend.log` for `uiautomation` errors

### Screen Recording Files Won't Play

- Ensure `opencv-python` is installed
- Check available disk space on `C:\ProgramData\`
- Files use the `mp4v` (XVID) codec — try **VLC** if Windows Media Player fails

### PyInstaller Build Fails

```cmd
rmdir /s /q backend-windows\build
rmdir /s /q backend-windows\dist
pip install --upgrade pyinstaller
cd backend-windows
python -m PyInstaller --onefile --noconsole main.py
```

---

## 🚨 Important Notes

1. **🔑 Change default password** — `admin` / `Admin@123` must be changed on first login
2. **🔐 Rotate the JWT secret** — edit `SECRET_KEY` in `auth/auth_manager.py` before any production deployment
3. **📁 Secure `users.json`** — credentials are stored in plain text; restrict access with NTFS ACLs
4. **💾 Monitor disk usage** — screenshots use ~1–2 GB/week per user; video storage varies with recording hours
5. **🔒 Obtain consent** — keystroke logging and screen recording require explicit written employee consent in most jurisdictions
6. **🌐 Network required for sync** — ERP endpoints must be reachable for data to leave the device
7. **🎥 Screen recording is OFF by default** — it must be explicitly enabled by an admin
8. **🪟 Windows only** — `pywin32`, `uiautomation`, and `pynput._win32` make this backend Windows-specific
9. **🔒 Localhost only** — the backend API is intentionally bound to `127.0.0.1`

---

## 📚 Further Documentation

- **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** — full deployment walkthrough, ERP integration patterns, troubleshooting
- **Swagger UI** — `http://localhost:51235/docs`
- **ReDoc** — `http://localhost:51235/redoc`

---

## 📞 Support & Logs

| Resource | Location |
|---|---|
| Main application log | `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log` |
| Service stdout | `C:\ProgramData\EnterpriseMonitor\logs\backend_stdout.log` |
| Service stderr | `C:\ProgramData\EnterpriseMonitor\logs\backend_stderr.log` |
| Health check | `curl http://localhost:51235/health` |
| API documentation | `http://localhost:51235/docs` |
| Service status | `nssm status EnterpriseMonitorBackend` |

---

## 📄 License

**PROPRIETARY** — Internal use only.  
Developed by **Ashraful Anik** / Skillers Zone LTD.

---

**Version**: 2.0.0 &nbsp;|&nbsp; **Platform**: Windows 10/11 (x64) &nbsp;|&nbsp; **Last Updated**: February 2026
