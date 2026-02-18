# Enterprise Monitor

**Professional Employee Monitoring System for Windows**

A comprehensive, production-ready monitoring solution built with Electron, Python FastAPI, and modern web technologies. Designed for enterprise environments to track employee productivity, application usage, and system activity.

> **📌 Repository Note**: This repository is transitioning to use `main` as the default branch. See [BRANCH_MERGE_INSTRUCTIONS.md](BRANCH_MERGE_INSTRUCTIONS.md) for details on the branch consolidation process.

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
- **Clipboard Monitoring**: Track clipboard events for security auditing
- **Central Server Sync**: Automatic data synchronization to ERP server
- **Admin Dashboard**: Modern web-based interface for viewing analytics
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
│  │           MONITORING SERVICES                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │   │
│  │  │ Screenshot  │  │ App Tracker │  │  Clipboard  │  │   │
│  │  │  Monitor    │  │   Service   │  │   Monitor   │  │   │
│  │  │  (5s cycle) │  │  (5s cycle) │  │ (Real-time) │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │   │
│  │  ┌─────────────┐  ┌─────────────┐                   │   │
│  │  │   Cleanup   │  │    Sync     │                   │   │
│  │  │   Service   │  │   Service   │                   │   │
│  │  │ (24h cycle) │  │ (60s cycle) │                   │   │
│  │  └─────────────┘  └─────────────┘                   │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
│  ┌──────────────┴───────────────────────────────────────┐   │
│  │              DATABASE LAYER                           │   │
│  │  • SQLite Database                                    │   │
│  │  • Tables: screenshots, app_activity, clipboard      │   │
│  │  • Sync tracking (synced flag)                       │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
└─────────────────┼────────────────────────────────────────────┘
                  │
                  │ HTTPS POST (Every 60s)
                  │
┌─────────────────┼────────────────────────────────────────────┐
│                 ▼                                            │
│        ERP SERVER (External)                                 │
│  https://api.erp.skillerszone.com/api/pctracking/appuseage  │
│  • Receives app activity data                               │
│  • Centralized monitoring dashboard                         │
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
  - `data_cleaner.py`: Deletes data older than 7 days (runs every 24 hours)

- **Services** (`services/`):
  - `sync_service.py`: Syncs app activity to ERP server every 60 seconds

- **Database** (`database/`):
  - `db_manager.py`: SQLite operations, schema management, migrations

- **Authentication** (`auth/`):
  - `auth_manager.py`: JWT token generation/validation, password hashing (bcrypt)

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
| **mss** | Latest | Screenshot capture |
| **Pillow** | Latest | Image processing |
| **pyperclip** | Latest | Clipboard monitoring |
| **psutil** | Latest | Process/system utilities |
| **pywin32** | Latest | Windows API access |
| **requests** | Latest | HTTP client for ERP sync |

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
- **Metadata**: Stores timestamp, file path, active window, active app in database
- **Sync Flag**: Tracks which screenshots have been synced to server

### 2. **Application Tracking**
- **Interval**: Every 5 seconds
- **Data Captured**:
  - Application name (e.g., `chrome.exe`, `WINWORD.EXE`)
  - Window title (e.g., "Document1 - Microsoft Word")
  - Duration in seconds
  - Timestamp
- **Purpose**: Productivity analytics, time tracking
- **Sync**: Automatically synced to ERP server

### 3. **Clipboard Monitoring**
- **Mode**: Real-time event-based
- **Data Captured**:
  - Content type (text, image, file)
  - Content preview (first 100 characters for text)
  - Timestamp
- **Purpose**: Security auditing, data leak prevention
- **Privacy**: Only stores preview, not full content

### 4. **Central Server Synchronization**
- **Endpoint**: `https://api.erp.skillerszone.com/api/pctracking/appuseage`
- **Interval**: Every 60 seconds (configurable)
- **Data Synced**: App activity records
- **Payload Format**:
  ```json
  {
    "pcName": "DESKTOP-ABC123",
    "appName": "chrome.exe",
    "windowsTitle": "GitHub - Google Chrome",
    "startTime": "2026-02-17T12:00:00Z",
    "endTime": "2026-02-17T12:00:05Z",
    "duration": "5",
    "syncTime": "2026-02-17T12:01:00Z"
  }
  ```
- **Retry Logic**: Failed syncs are retried in next cycle
- **Batch Size**: 50 records per sync

### 5. **Automated Data Cleanup**
- **Schedule**: Every 24 hours
- **Retention**: 7 days (configurable)
- **Scope**: Deletes old screenshots, app activity, clipboard events
- **Purpose**: Manage disk space, comply with data retention policies

### 6. **Admin Dashboard**
- **Authentication**: JWT-based login
- **Default Credentials**: `admin` / `admin123` (⚠️ Change in production!)
- **Features**:
  - Real-time statistics (screenshots, active hours, apps tracked, clipboard events)
  - Date picker for historical data
  - Activity charts (timeline, app usage, category breakdown)
  - Detailed logs (app tracking, browser tracking, clipboard tracking)
  - Screenshot gallery
  - Monitoring controls (pause/resume)

### 7. **System Tray Integration**
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

All data is stored in the user's local application data folder:

**Base Directory**: `%LOCALAPPDATA%\EnterpriseMonitor\`

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

### Database Schema

**SQLite Database**: `monitoring.db`

#### Table: `screenshots`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| file_path | TEXT | Absolute path to screenshot file |
| active_window | TEXT | Window title at capture time |
| active_app | TEXT | Application name at capture time |
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
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

#### Table: `clipboard_events`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| timestamp | TEXT | ISO-8601 timestamp |
| content_type | TEXT | Type of clipboard content |
| content_preview | TEXT | Preview of content (max 100 chars) |
| created_at | TEXT | Record creation timestamp |
| synced | INTEGER | 0 = not synced, 1 = synced to server |

### Configuration File

**File**: `config.json`

```json
{
  "server_url": "",
  "api_key": "",
  "device_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "sync_interval_seconds": 60,
  "screenshot_interval": 60
}
```

### Data Synchronization Flow

```
┌─────────────────────────────────────────────────────────────┐
│  1. MONITORING SERVICES COLLECT DATA                        │
│     • Screenshot Monitor captures screen every 5s           │
│     • App Tracker logs active app every 5s                  │
│     • Clipboard Monitor detects clipboard changes           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  2. DATA STORED IN LOCAL SQLite DATABASE                    │
│     • INSERT with synced = 0                                │
│     • Metadata stored (timestamp, app, window, etc.)        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  3. SYNC SERVICE RUNS (Every 60 seconds)                    │
│     • Query: SELECT * FROM app_activity WHERE synced = 0    │
│     • Batch size: 50 records                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  4. POST TO ERP SERVER                                      │
│     • URL: https://api.erp.skillerszone.com/...             │
│     • Payload: JSON with pcName, appName, timestamps, etc.  │
│     • Timeout: 10 seconds                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  5. MARK AS SYNCED ON SUCCESS                               │
│     • UPDATE app_activity SET synced = 1 WHERE id IN (...)  │
│     • Failed records remain synced = 0 for retry            │
└─────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  6. CLEANUP SERVICE (Every 24 hours)                        │
│     • DELETE FROM * WHERE timestamp < (now - 7 days)        │
│     • Frees disk space                                      │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoints

#### Authentication
- `POST /api/auth/login` - Login with username/password, returns JWT token
- `GET /api/auth/check` - Verify JWT token validity
- `POST /api/auth/change-password` - Change user password

#### Statistics
- `GET /api/statistics?date=YYYY-MM-DD` - Get statistics for specific date
- `GET /api/stats/activity?start=YYYY-MM-DD&end=YYYY-MM-DD` - Activity stats for date range
- `GET /api/stats/timeline?date=YYYY-MM-DD` - Timeline data for specific date

#### Screenshots
- `GET /api/screenshots?limit=20&offset=0` - Get screenshot records (paginated)

#### Data Logs
- `GET /api/data/apps?limit=50&offset=0` - Get app activity logs
- `GET /api/data/browser?limit=50&offset=0` - Get browser activity logs
- `GET /api/data/clipboard?limit=50&offset=0` - Get clipboard event logs

#### Monitoring Control
- `GET /api/monitoring/status` - Get monitoring status (active/paused)
- `POST /api/monitoring/pause` - Pause monitoring services
- `POST /api/monitoring/resume` - Resume monitoring services

#### Configuration
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration (server_url, api_key, sync_interval)

#### Health
- `GET /health` - Health check endpoint
- `GET /` - API info and version

---

## 🚀 Quick Start

### Prerequisites
- **Windows 10/11**
- **Python 3.11+** ([Download](https://www.python.org/downloads/))
- **Node.js 18+** ([Download](https://nodejs.org/))

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
│   │       ├── index.html        # Dashboard UI
│   │       └── renderer.js       # Dashboard logic & charts
│   ├── package.json              # Node dependencies & build scripts
│   └── tsconfig.json             # TypeScript configuration
│
├── backend-windows/              # Python backend for Windows
│   ├── api_server.py             # FastAPI application & routes
│   ├── main.py                   # Entry point, starts Uvicorn server
│   ├── requirements.txt          # Python dependencies
│   ├── auth/
│   │   └── auth_manager.py       # JWT & password management
│   ├── database/
│   │   └── db_manager.py         # SQLite operations
│   ├── monitoring/
│   │   ├── screenshot.py         # Screenshot capture service
│   │   ├── app_tracker.py        # Application tracking service
│   │   ├── clipboard.py          # Clipboard monitoring service
│   │   └── data_cleaner.py       # Automated cleanup service
│   ├── services/
│   │   └── sync_service.py       # ERP server synchronization
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

### Data Security
- **Local Storage**: All data stored locally on user machine
- **HTTPS**: ERP sync uses HTTPS
- **No Cloud Storage**: Screenshots stored locally only
- **Access Control**: Admin-only access to dashboard

### Privacy Considerations
⚠️ **Legal Compliance Required**:
- Inform employees about monitoring
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
# Line 18
def __init__(self, db_manager, interval_seconds: int = 5):
    self.interval_seconds = 300  # Change to 300 for 5 minutes
```

### Change Sync Interval
Edit `backend-windows/services/sync_service.py`:
```python
# Line 32
DEFAULT_SYNC_INTERVAL = 300  # Change to desired seconds
```

Or update via API:
```bash
curl -X POST http://localhost:51235/api/config \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sync_interval_seconds": 300}'
```

### Change Data Retention Period
Edit `backend-windows/monitoring/data_cleaner.py` to modify the 7-day default.

---

## 🚨 Important Notes

1. **⚠️ Change Default Password**: The default `admin/admin123` credentials are for initial setup only
2. **💾 Disk Space**: Monitor screenshot storage, ~1-2GB per week per user
3. **🔒 Privacy**: Ensure legal compliance before deployment
4. **🌐 Network**: ERP sync requires internet connectivity
5. **🪟 Windows Only**: This build is optimized for Windows; macOS support is experimental

---

## 📄 License

**PROPRIETARY** - Internal use only

---

## 📞 Support

- **Logs**: `%LOCALAPPDATA%\EnterpriseMonitor\logs\backend.log`
- **Health Check**: `curl http://localhost:51235/health`
- **API Docs**: `http://localhost:51235/docs`

---

**Version**: 1.0.0  
**Platform**: Windows 10/11  
**Last Updated**: February 2026  
**Built by**: Skillers Zone LTD
