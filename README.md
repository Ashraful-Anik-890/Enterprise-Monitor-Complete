# Enterprise Monitor

**Professional Employee Monitoring System for Windows**

A comprehensive, production-ready monitoring solution built with Electron, Python FastAPI, and modern web technologies. Designed for enterprise environments to track employee productivity, application usage, browser activity, keystrokes, screen recordings, and system activity.

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Technology Stack](#-technology-stack)
- [Key Features](#-key-features)
- [Data Flow & Storage](#-data-flow--storage)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Security](#-security)
- [Documentation](#-documentation)

---

## 🎯 Overview

Enterprise Monitor is a **Windows-focused** employee monitoring system that provides:

- **Real-time Activity Tracking**: Monitor active applications, windows, and user behavior
- **Screenshot Capture**: Automated screenshots with configurable intervals
- **Browser URL Tracking**: Real-time tracking of browser URLs via Windows UI Automation
- **Keystroke Logging**: Buffered text input logging with privacy filter
- **Screen Recording**: Chunked MP4 video recording at 720p/10 FPS
- **Clipboard Monitoring**: Track clipboard events for security auditing
- **Central Server Sync**: Automatic synchronization of **6 data types** to per-type ERP endpoints
- **Admin Dashboard**: Modern web-based interface for viewing analytics and configuring endpoints
- **System Tray Integration**: Lightweight, non-intrusive background operation

### Platform Support

- **Primary**: Windows 10/11 (Fully functional)
- **Secondary**: macOS 13+ (Basic backend support available in `backend-macos/`)

> **Note**: This README focuses on the Windows implementation as it's the primary deployment target.

---

## 🏗️ Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ELECTRON APP (GUI)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Main Process│  │   Renderer   │  │  System Tray │     │
│  │  (Node.js)   │  │  (HTML/CSS/JS)│  │   Manager    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                            │                                 │
│                    IPC Communication                         │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                   HTTP REST API (Port 51235)
                             │
┌────────────────────────────┼─────────────────────────────────┐
│              PYTHON BACKEND (FastAPI)                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  API Server                           │   │
│  │  • Authentication (JWT)                               │   │
│  │  • RESTful Endpoints                                  │   │
│  │  • CORS Middleware                                    │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
│  ┌──────────────┴───────────────────────────────────────┐   │
│  │           MONITORING SERVICES (6 active)              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │   │
│  │  │ Screenshot │  │ App Tracker│  │   Clipboard    │  │   │
│  │  │  Monitor   │  │  Service   │  │    Monitor     │  │   │
│  │  │ (5s cycle) │  │ (5s cycle) │  │  (Real-time)   │  │   │
│  │  └────────────┘  └────────────┘  └────────────────┘  │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │   │
│  │  │  Browser   │  │ Keylogger  │  │ Screen Recorder│  │   │
│  │  │  Tracker   │  │  Service   │  │ (Admin toggle) │  │   │
│  │  │ (5s cycle) │  │ (pynput)   │  │ 720p/10FPS MP4 │  │   │
│  │  └────────────┘  └────────────┘  └────────────────┘  │   │
│  │  ┌────────────┐  ┌────────────┐                      │   │
│  │  │  Cleanup   │  │  Sync v2   │                      │   │
│  │  │  Service   │  │  Service   │                      │   │
│  │  │ (24h cycle)│  │(300s cycle)│                      │   │
│  │  └────────────┘  └────────────┘                      │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
│  ┌──────────────┴───────────────────────────────────────┐   │
│  │              DATABASE LAYER (SQLite)                  │   │
│  │  • screenshots   • app_activity   • clipboard_events  │   │
│  │  • browser_activity  • text_logs  • video_recordings  │   │
│  │  • device_config (identity KV store)                  │   │
│  │  • Sync tracking (synced flag on all data tables)     │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
└─────────────────┼────────────────────────────────────────────┘
                  │
                  │ HTTPS POST (Every 300s, per-type endpoints)
                  │
┌─────────────────┼────────────────────────────────────────────┐
│                 ▼                                            │
│        ERP SERVER (External) — 6 separate endpoints         │
│  • url_app_activity  → POST JSON (app usage sessions)       │
│  • url_browser       → POST JSON (browser URL visits)       │
│  • url_clipboard     → POST JSON (clipboard events)         │
│  • url_keystrokes    → POST JSON (keystroke / text logs)    │
│  • url_screenshots   → POST multipart (PNG files)           │
│  • url_videos        → POST multipart (MP4 chunks)          │
└──────────────────────────────────────────────────────────────┘
```

### Component Breakdown

#### 1. **Electron App** (`electron-app/`)
- **Main Process** (`src/main/main.ts`): 
  - Manages application lifecycle
  - Creates browser windows
  - Handles IPC communication
  - Manages system tray
  - Auto-starts on Windows login
  
- **Renderer Process** (`src/renderer/`):
  - Dashboard UI (HTML/CSS/JavaScript)
  - Chart.js for data visualization
  - Date picker for historical data
  - Real-time statistics display
  - **"Config Server API" modal**: Configure per-type ERP endpoint URLs, API key, and sync interval

- **Preload Script** (`src/preload/`):
  - Secure bridge between main and renderer
  - Exposes safe APIs to renderer

#### 2. **Python Backend** (`backend-windows/`)
- **API Server** (`api_server.py`):
  - FastAPI application
  - JWT authentication
  - RESTful endpoints
  - CORS enabled for Electron

- **Monitoring Services** (`monitoring/`):
  - `screenshot.py`: Captures screenshots every 5 seconds, optimizes to 60-80KB
  - `app_tracker.py`: Tracks active application and window title every 5 seconds
  - `clipboard.py`: Monitors clipboard changes in real-time
  - `browser_tracker.py`: Reads browser address bar via Windows UI Automation (Chrome, Edge, Firefox, Brave, Opera, and more)
  - `keylogger.py`: Buffers keystrokes per window, flushes on Enter or window switch; skips password/login fields
  - `screen_recorder.py`: Captures primary display as 5-minute 720p MP4 chunks at 10 FPS (admin-controlled)
  - `data_cleaner.py`: Deletes data older than 7 days (runs every 24 hours)

- **Services** (`services/`):
  - `sync_service.py` (v2): Syncs **6 data types** to their respective ERP endpoints every 300 seconds

- **Database** (`database/`):
  - `db_manager.py`: SQLite operations, schema management, migrations

- **Authentication** (`auth/`):
  - `auth_manager.py`: JWT token generation/validation, password hashing (bcrypt), security Q&A, credential updates

- **Configuration** (`utils/`):
  - `config_manager.py`: Persistent config storage (JSON)

---

## 🛠️ Technology Stack

### Frontend (Electron App)
| Technology | Version | Purpose |
|------------|---------|---------|
| **Electron** | 28.x | Cross-platform desktop framework |
| **TypeScript** | 5.3.x | Type-safe JavaScript |
| **Chart.js** | Latest | Data visualization (charts, graphs) |
| **Axios** | 1.6.x | HTTP client for API calls |
| **electron-store** | 8.1.x | Persistent local storage |

### Backend (Windows)
| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.11+ | Backend runtime |
| **FastAPI** | Latest | Modern async web framework |
| **Uvicorn** | Latest | ASGI server |
| **SQLite** | 3.x | Embedded database |
| **python-jose** | Latest | JWT token handling |
| **passlib** | Latest | Password hashing (bcrypt) |
| **mss** | Latest | Screenshot & screen recording capture |
| **Pillow** | Latest | Image processing |
| **opencv-python** | Latest | MP4 video encoding (XVID/mp4v) |
| **numpy** | Latest | Frame array processing for video |
| **pyperclip** | Latest | Clipboard monitoring |
| **psutil** | Latest | Process/system utilities |
| **pywin32** | Latest | Windows API access |
| **uiautomation** | Latest | Browser address bar reading (UI Automation COM) |
| **pynput** | Latest | Keyboard event hook for keystroke logging |
| **requests** | Latest | HTTP client for ERP sync |
| **tzdata** | Latest | IANA timezone database for Windows |

### Build & Deployment
| Tool | Purpose |
|------|---------|
| **electron-builder** | Create Windows installer (NSIS) |
| **TypeScript Compiler** | Compile TS to JS |
| **npm** | Package management |

---

## ✨ Key Features

### 1. **Screenshot Monitoring**
- **Interval**: Every 5 seconds (configurable in `screenshot.py`)
- **Optimization**: Automatically compressed to 60-80KB per image
- **Storage**: Local filesystem (`%LOCALAPPDATA%\EnterpriseMonitor\screenshots\`)
- **Metadata**: Stores timestamp, file path, active window, active app, username in database
- **Sync**: Uploaded as multipart/form-data to configured `url_screenshots` endpoint

### 2. **Application Tracking**
- **Interval**: Every 5 seconds
- **Data Captured**:
  - Application name (e.g., `chrome.exe`, `WINWORD.EXE`)
  - Window title (e.g., "Document1 - Microsoft Word")
  - Duration in seconds
  - Username
  - Timestamp
- **Purpose**: Productivity analytics, time tracking
- **Sync**: Automatically synced as JSON to `url_app_activity` endpoint

### 3. **Browser URL Tracking** *(New)*
- **Method**: Windows UI Automation API — reads browser address bar directly (no proxy, no extension needed)
- **Supported Browsers**: Chrome, Edge, Firefox, Brave, Opera, Opera GX, Yandex Browser, DuckDuckGo, UC Browser, Vivaldi, Cent Browser, 360 Browser, Waterfox, LibreWolf, Thunderbird *(email client — tracked because it exposes an address bar via UI Automation)*
- **Data Captured**:
  - Browser name
  - Full URL
  - Page title
  - Username
  - Timestamp
- **Sync**: Automatically synced as JSON to `url_browser` endpoint

### 4. **Keystroke / Text Logging** *(New)*
- **Method**: `pynput` keyboard listener (OS-level event hook, non-suppressing)
- **Buffering**: Keystrokes are buffered per active window and flushed on Enter key or window switch
- **Privacy Filter**: Logging is suspended when the active window title contains `password`, `login`, `sign in`, `signin`, or `credentials`
- **Data Captured**:
  - Application name
  - Window title
  - Buffered text content
  - Username
  - Timestamp
- **Sync**: Automatically synced as JSON to `url_keystrokes` endpoint

### 5. **Clipboard Monitoring**
- **Mode**: Real-time event-based
- **Data Captured**:
  - Content type (text, image, file)
  - Content preview (first 100 characters for text)
  - Username
  - Timestamp
- **Purpose**: Security auditing, data leak prevention
- **Privacy**: Only stores preview, not full content
- **Sync**: Automatically synced as JSON to `url_clipboard` endpoint

### 6. **Screen Recording** *(New)*
- **Control**: Admin-toggled via dashboard or `POST /api/monitoring/video/toggle`
- **Format**: MP4 (XVID/mp4v codec), 5-minute rolling chunks
- **Resolution**: 1280×720 (720p) at 10 FPS
- **Storage**: `C:\ProgramData\EnterpriseMonitor\videos\`
- **Metadata**: Duration, timestamp, file path stored in `video_recordings` table
- **Sync**: Uploaded as multipart/form-data to configured `url_videos` endpoint

### 7. **Central Server Synchronization (v2 — 6 Types)**
- **Interval**: Every 300 seconds (configurable)
- **Manual Trigger**: `POST /api/sync/trigger`
- **Per-Type Endpoint Configuration** (set via "Config Server API" modal in dashboard):

| Config Key | Method | Data Type |
|---|---|---|
| `url_app_activity` | POST JSON | App usage sessions |
| `url_browser` | POST JSON | Browser URL visits |
| `url_clipboard` | POST JSON | Clipboard events |
| `url_keystrokes` | POST JSON | Keystroke / text logs |
| `url_screenshots` | POST multipart | PNG screenshot files |
| `url_videos` | POST multipart | MP4 video chunk files |

- **Authentication**: Optional shared `X-API-Key` header sent to all endpoints
- **Batch Sizes**: 50 records for JSON types; 10 files for screenshots; 3 files for videos
- **Retry Logic**: Failed syncs leave `synced = 0`; retried in next cycle
- **App Activity Payload Example**:
  ```json
  {
    "pcName": "DESKTOP-ABC123",
    "appName": "chrome.exe",
    "windowsTitle": "GitHub - Google Chrome",
    "startTime": "2026-02-17T12:00:00Z",
    "endTime": "2026-02-17T12:00:05Z",
    "duration": 5,
    "syncTime": "2026-02-17T12:05:00Z"
  }
  ```

### 8. **Automated Data Cleanup**
- **Schedule**: Every 24 hours
- **Retention**: 7 days (configurable)
- **Scope**: Deletes old screenshots, app activity, browser activity, clipboard events, text logs
- **Purpose**: Manage disk space, comply with data retention policies

### 9. **Admin Dashboard**
- **Authentication**: JWT-based login
- **Default Credentials**: `admin` / `admin123` (⚠️ Change in production!)
- **Features**:
  - Real-time statistics (screenshots, active hours, apps tracked, clipboard events)
  - Date picker for historical data
  - Activity charts (timeline, app usage, category breakdown)
  - Detailed logs (app tracking, browser tracking, keystroke logs, clipboard tracking)
  - Screenshot gallery
  - Video recordings list
  - Monitoring controls (pause/resume all services)
  - Video recording toggle (enable/disable screen recorder)
  - **"Config Server API" modal**: Configure per-type ERP endpoint URLs, API key, sync interval

### 10. **Identity Management** *(New)*
- **Device Alias**: Custom name for the monitored PC (overrides hostname in sync payloads)
- **User Alias**: Custom display name for the monitored user (overrides OS username)
- **Endpoints**: `GET /api/config/identity` and `POST /api/config/identity`

### 11. **System Tray Integration**
- **Auto-start**: Launches on Windows login
- **Background Operation**: Runs silently in system tray
- **Tray Menu**:
  - Open Dashboard
  - Backend Status Indicator
  - Auth Status Indicator
  - Quit Application

---

## 💾 Data Flow & Storage

### Local Storage Locations

**Screenshots & Database** (`%LOCALAPPDATA%\EnterpriseMonitor\`):

```
C:\Users\{Username}\AppData\Local\EnterpriseMonitor\
├── monitoring.db          # SQLite database
├── config.json            # Configuration file
├── logs\
│   └── backend.log        # Application logs
└── screenshots\
    ├── screenshot_20260217_120000.jpg
    ├── screenshot_20260217_120005.jpg
    └── ...
```

**Video Recordings** (`%PROGRAMDATA%\EnterpriseMonitor\videos\`):

```
C:\ProgramData\EnterpriseMonitor\videos\
├── recording_20260217_120000.mp4   # 5-minute chunk
├── recording_20260217_120500.mp4
└── ...
```

### Database Schema

**SQLite Database**: `monitoring.db`

> All tracking tables include a `username TEXT DEFAULT ''` column and a `synced INTEGER DEFAULT 0` column.

#### Table: `screenshots`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| file_path | TEXT | Absolute path to screenshot file |
| active_window | TEXT | Window title at capture time |
| active_app | TEXT | Application name at capture time |
| username | TEXT | OS username at capture time |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `app_activity`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| app_name | TEXT | Application executable name |
| window_title | TEXT | Window title |
| duration_seconds | INTEGER | Duration of activity |
| username | TEXT | OS username |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `clipboard_events`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| content_type | TEXT | Type of clipboard content |
| content_preview | TEXT | Preview of content (max 100 chars) |
| username | TEXT | OS username |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `browser_activity` *(New)*
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| browser_name | TEXT | Browser display name (e.g., "Chrome") |
| url | TEXT | Full URL visited |
| page_title | TEXT | Page title |
| username | TEXT | OS username |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `text_logs` *(New)*
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| application | TEXT | Application executable name |
| window_title | TEXT | Window title at time of capture |
| content | TEXT | Buffered keystroke text |
| username | TEXT | OS username |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `video_recordings` *(New)*
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp (recording start) |
| file_path | TEXT | Absolute path to MP4 file |
| duration_seconds | INTEGER | Length of the recording chunk |
| is_synced | INTEGER | 0 = not synced, 1 = synced to server |
| created_at | TEXT | Record creation timestamp |

#### Table: `device_config` *(New)*
| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PRIMARY KEY | Config key (`device_alias`, `user_alias`) |
| value | TEXT | Config value |

### Configuration File

**File**: `config.json`

```json
{
  "api_key": "",
  "sync_interval_seconds": 300,
  "url_app_activity": "",
  "url_browser": "",
  "url_clipboard": "",
  "url_keystrokes": "",
  "url_screenshots": "",
  "url_videos": "",
  "server_url": "",
  "recording_enabled": false,
  "timezone": "UTC"
}
```

> `server_url` is kept for backward compatibility with older installations. New deployments should use the per-type URL fields.

### Data Synchronization Flow

```
┌─────────────────────────────────────────────────────────────┐
│  1. MONITORING SERVICES COLLECT DATA (6 types)              │
│     • Screenshot Monitor → screenshots table (every 5s)     │
│     • App Tracker        → app_activity table (every 5s)    │
│     • Browser Tracker    → browser_activity table           │
│     • Keylogger          → text_logs table                  │
│     • Clipboard Monitor  → clipboard_events table           │
│     • Screen Recorder    → video_recordings table + MP4     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  2. DATA STORED IN LOCAL SQLite DATABASE                    │
│     • INSERT with synced = 0                                │
│     • Metadata stored (timestamp, app, window, username…)   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  3. SYNC SERVICE v2 RUNS (Every 300 seconds)                │
│     • For each of 6 types: query WHERE synced = 0           │
│     • Batches: 50 JSON records / 10 screenshots / 3 videos  │
│     • Sends to per-type configured endpoint URL             │
│     • JSON types → POST application/json                    │
│     • File types → POST multipart/form-data                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  4. MARK AS SYNCED ON SUCCESS                               │
│     • UPDATE <table> SET synced = 1 WHERE id IN (...)       │
│     • Failed records remain synced = 0 for retry            │
│     • Missing files (cleaned up) also marked synced         │
└─────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  5. CLEANUP SERVICE (Every 24 hours)                        │
│     • DELETE FROM * WHERE timestamp < (now - 7 days)        │
│     • Covers all 5 data tables + screenshots on disk        │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoints

#### Authentication
- `POST /api/auth/login` - Login with username/password, returns JWT token
- `GET /api/auth/check` - Verify JWT token validity
- `POST /api/auth/change-password` - Change user password
- `POST /api/auth/update-credentials` - Update username, password, and security Q&A *(New)*

#### Statistics
- `GET /api/statistics?date=YYYY-MM-DD` - Get statistics for specific date
- `GET /api/stats/activity?start=YYYY-MM-DD&end=YYYY-MM-DD` - Activity stats for date range
- `GET /api/stats/timeline?date=YYYY-MM-DD` - Timeline data for specific date

#### Screenshots
- `GET /api/screenshots?limit=20&offset=0` - Get screenshot records (paginated)

#### Data Logs
- `GET /api/data/apps?limit=50&offset=0` - Get app activity logs
- `GET /api/data/browser?limit=50&offset=0` - Get browser activity logs
- `GET /api/data/keylogs?limit=100&offset=0` - Get keystroke / text logs *(New)*
- `GET /api/data/clipboard?limit=50&offset=0` - Get clipboard event logs
- `GET /api/data/videos?limit=50` - Get video recording list *(New)*

#### Monitoring Control
- `GET /api/monitoring/status` - Get monitoring status (active/paused)
- `POST /api/monitoring/pause` - Pause all monitoring services (including browser tracker & keylogger)
- `POST /api/monitoring/resume` - Resume all monitoring services
- `POST /api/monitoring/video/toggle` - Enable or disable screen recording *(New)*
- `GET /api/monitoring/video/status` - Get screen recording status *(New)*

#### Configuration
- `GET /api/config` - Get current configuration (all fields including per-type URLs)
- `POST /api/config` - Update configuration (api_key, sync_interval_seconds, per-type URLs, server_url)
- `GET /api/config/identity` - Get device identity (machine_id, os_user, device_alias, user_alias) *(New)*
- `POST /api/config/identity` - Update device_alias and/or user_alias *(New)*
- `GET /api/config/timezone` - Get display timezone *(New)*
- `POST /api/config/timezone` - Set display timezone (IANA string) *(New)*

#### Sync
- `POST /api/sync/trigger` - Manually trigger a full 6-type sync cycle *(New)*

#### Health
- `GET /health` - Health check endpoint
- `GET /` - API info and version

---

## 🚀 Quick Start

### Prerequisites
- **Windows 10/11**
- **Python 3.11+** ([Download](https://www.python.org/downloads/))
- **Node.js 18+** ([Download](https://nodejs.org/))
- **Visual C++ Redistributable 2015–2022** (required by `uiautomation` for browser tracking — [Download](https://aka.ms/vs/17/release/vc_redist.x64.exe))

### 1. Setup Backend
```cmd
cd backend-windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Backend will start on `http://127.0.0.1:51235`

### 2. Setup Electron App
```cmd
cd electron-app
npm install
npm run build
npm start
```

### 3. Login
- **Username**: `admin`
- **Password**: `admin123`

⚠️ **Change default password immediately in production!**

### 4. Configure ERP Endpoints
Open the **"Config Server API"** modal from the dashboard to set per-type endpoint URLs, your API key, and sync interval.

---

## 📁 Project Structure

```
enterprise-monitor-complete/
├── electron-app/                 # Electron GUI application
│   ├── dist/                     # Compiled TypeScript output
│   ├── node_modules/             # Node dependencies
│   ├── resources/                # App icons
│   ├── src/
│   │   ├── main/
│   │   │   ├── main.ts           # Main process entry point
│   │   │   ├── api-client.ts     # HTTP client for backend API
│   │   │   └── tray.ts           # System tray manager
│   │   ├── preload/
│   │   │   └── preload.ts        # Secure IPC bridge
│   │   └── renderer/
│   │       ├── index.html        # Dashboard UI (incl. Config Server API modal)
│   │       └── renderer.js       # Dashboard logic & charts
│   ├── package.json              # Node dependencies & build scripts
│   └── tsconfig.json             # TypeScript configuration
│
├── backend-windows/              # Python backend for Windows
│   ├── api_server.py             # FastAPI application & routes
│   ├── main.py                   # Entry point, starts Uvicorn server
│   ├── requirements.txt          # Python dependencies
│   ├── auth/
│   │   └── auth_manager.py       # JWT, password management, security Q&A
│   ├── database/
│   │   └── db_manager.py         # SQLite operations & migrations
│   ├── monitoring/
│   │   ├── screenshot.py         # Screenshot capture service
│   │   ├── app_tracker.py        # Application tracking service
│   │   ├── browser_tracker.py    # Browser URL tracking (UI Automation)
│   │   ├── keylogger.py          # Keystroke / text logging service
│   │   ├── screen_recorder.py    # Screen video recorder (MP4 chunks)
│   │   ├── clipboard.py          # Clipboard monitoring service
│   │   └── data_cleaner.py       # Automated cleanup service
│   ├── services/
│   │   └── sync_service.py       # ERP synchronization (v2 — 6 types)
│   └── utils/
│       └── config_manager.py     # Configuration management
│
├── backend-macos/                # Swift backend for macOS (optional)
│   └── (Swift/Vapor implementation)
│
├── scripts/                      # Setup scripts
│   ├── setup-windows.bat         # Windows setup automation
│   └── setup-macos.sh            # macOS setup automation
│
├── README.md                     # This file
├── IMPLEMENTATION_GUIDE.md       # Detailed setup & deployment guide
└── .gitignore                    # Git ignore rules
```

---

## 🔐 Security

### Authentication
- **JWT Tokens**: Secure, stateless authentication
- **Password Hashing**: bcrypt with salt
- **Token Expiration**: 24 hours (configurable)
- **Default Credentials**: `admin` / `admin123` (⚠️ **MUST CHANGE**)
- **Security Q&A**: Stored alongside credentials for account recovery

### Data Security
- **Local Storage**: All database and screenshot data stored locally on user machine
- **Video Storage**: MP4 recordings stored in `%PROGRAMDATA%` with restricted ACLs (set by installer)
- **HTTPS**: ERP sync uses HTTPS for all endpoint communications
- **No Cloud Storage**: Files stored locally; only synced on-demand to configured endpoints
- **Access Control**: Admin-only access to dashboard
- **Keystroke Privacy Filter**: Keylogger automatically suppresses capture on password/login windows

### Privacy Considerations
⚠️ **Legal Compliance Required**:
- Inform employees about monitoring (screenshots, browser URLs, keystrokes, screen recording)
- Obtain consent where legally required
- Comply with GDPR, CCPA, and local laws
- Implement data retention policies
- Provide data access/deletion mechanisms

---

## 📚 Documentation

- **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)**: Complete setup, deployment, and troubleshooting guide
- **API Documentation**: Available at `http://localhost:51235/docs` when backend is running
- **Logs**: Check `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log` for debugging

---

## 🔧 Configuration

### Change Screenshot Interval
Edit `backend-windows/monitoring/screenshot.py`:
```python
def __init__(self, db_manager, interval_seconds: int = 5):
    self.interval_seconds = 300  # Change to 300 for 5 minutes
```

### Change Sync Interval
Edit `backend-windows/services/sync_service.py`:
```python
DEFAULT_SYNC_INTERVAL = 300  # Change to desired seconds
```

Or update via API:
```bash
curl -X POST http://localhost:51235/api/config \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sync_interval_seconds": 600}'
```

### Configure Per-Type ERP Endpoints
Use the dashboard **"Config Server API"** modal, or update via API:
```bash
curl -X POST http://localhost:51235/api/config \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "YOUR_KEY",
    "url_app_activity": "https://erp.example.com/api/app",
    "url_browser": "https://erp.example.com/api/browser",
    "url_clipboard": "https://erp.example.com/api/clipboard",
    "url_keystrokes": "https://erp.example.com/api/keystrokes",
    "url_screenshots": "https://erp.example.com/api/screenshots",
    "url_videos": "https://erp.example.com/api/videos"
  }'
```

### Set Device / User Alias
```bash
curl -X POST http://localhost:51235/api/config/identity \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_alias": "Finance-PC-01", "user_alias": "John Doe"}'
```

### Change Data Retention Period
Edit `backend-windows/monitoring/data_cleaner.py` to modify the 7-day default.

### Enable Screen Recording
Screen recording is **off by default**. Enable via the dashboard toggle or API:
```bash
curl -X POST http://localhost:51235/api/monitoring/video/toggle \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## 🚨 Important Notes

1. **⚠️ Change Default Password**: The default `admin/admin123` credentials are for initial setup only
2. **💾 Disk Space**: Monitor screenshot (~1-2 GB/week/user) and video storage (varies by recording hours)
3. **🔒 Privacy**: Ensure legal compliance before deployment — keylogger and screen recorder especially require employee consent
4. **🌐 Network**: ERP sync requires internet connectivity to configured endpoint URLs
5. **🪟 Windows Only**: This build is optimized for Windows; macOS support is experimental
6. **🎥 Screen Recording**: Not auto-started — must be explicitly enabled by an admin

---

## 📄 License

**PROPRIETARY** - Internal use only

---

## 📞 Support

- **Logs**: `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log`
- **Health Check**: `curl http://localhost:51235/health`
- **API Docs**: `http://localhost:51235/docs`

---

**Version**: 2.0.0  
**Platform**: Windows 10/11  
**Last Updated**: February 2026  
**Built by**: Skillers Zone LTD
