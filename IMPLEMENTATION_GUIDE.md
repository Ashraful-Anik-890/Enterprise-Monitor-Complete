# Enterprise Monitor - Implementation Guide

## 🎯 Quick Start

This is a complete, production-ready employee monitoring system with:
- ✅ Cross-platform Electron GUI (Windows + macOS)
- ✅ Native backends (Python for Windows, Swift for macOS)
- ✅ REST API architecture
- ✅ Screenshot capture, app tracking, clipboard monitoring
- ✅ Admin authentication
- ✅ SQLite database

---

## 📦 Project Structure

```
enterprise-monitor/
├── electron-app/          # Electron GUI (cross-platform)
├── backend-windows/       # Python backend for Windows
├── backend-macos/         # Swift backend for macOS
├── docs/                  # Documentation
└── scripts/               # Build scripts
```

---

## 🪟 WINDOWS SETUP

### Prerequisites

1. **Python 3.11+**
   - Download: https://www.python.org/downloads/
   - ✅ Check "Add Python to PATH" during installation

2. **Node.js 18+**
   - Download: https://nodejs.org/
   - Includes npm automatically

3. **Windows SDK** (for pywin32)
   - Included with Visual Studio Build Tools
   - Download: https://visualstudio.microsoft.com/downloads/

### Step 1: Setup Python Backend

```cmd
# Navigate to Windows backend directory
cd backend-windows

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# Install dependencies (including pywin32)
pip install -r requirements.txt

# Test backend (Port 51235)
python main.py
```

**Expected output:**
```
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:51235
```

**Test API:**
```cmd
# In another terminal
curl http://localhost:51235/health
```

### Step 2: Setup Electron App

```cmd
# Navigate to Electron app directory
cd electron-app

# Install dependencies
npm install

# Build TypeScript and Copy Assets
npm run build
xcopy /E /I src\renderer\index.html dist\renderer\

# Run application
npm start
```

### Step 3: Test the System

1. Backend should be running on http://localhost:51235
2. Electron app opens with system tray icon
3. Click tray icon → Login screen appears
4. Login with: **admin** / **Admin@123**
5. Dashboard shows (statistics may be zero initially)

### Step 4: Package for Distribution

```cmd
# Build Windows installer
cd electron-app
npm run dist:win
```

Output: `electron-app/release/Enterprise Monitor Setup.exe`

---

## 🍎 macOS SETUP

### Prerequisites

1. **Xcode Command Line Tools**
   ```bash
   xcode-select --install
   ```

2. **Swift 5.9+** (included with Xcode)
   ```bash
   swift --version
   ```

3. **Node.js 18+**
   ```bash
   # Install via Homebrew
   brew install node
   ```

### Step 1: Setup Swift Backend

```bash
# Navigate to macOS backend directory
cd backend-macos

# Resolve dependencies
swift package resolve

# Build project
swift build

# Run backend
swift run
```

**Expected output:**
```
✅ Enterprise Monitor Backend (macOS) starting...
📡 API Server listening on http://localhost:51234
✅ Routes registered
```

**Test API:**
```bash
# In another terminal
curl http://localhost:51234/health
```

### Step 2: Setup Electron App

```bash
# Navigate to Electron app directory
cd electron-app

# Install dependencies
npm install

# Build TypeScript
npm run build

# Run application
npm start
```

### Step 3: Grant Permissions

macOS requires explicit permissions:

1. **Screen Recording Permission**
   - Go to System Preferences → Privacy & Security → Screen Recording
   - Add the Enterprise Monitor app when prompted

2. **Accessibility Permission**
   - Go to System Preferences → Privacy & Security → Accessibility
   - Add the Enterprise Monitor app when prompted

### Step 4: Test the System

1. Backend running on http://localhost:51234
2. Electron app in menu bar (top right)
3. Click menu bar icon → Login
4. Credentials: **admin** / **Admin@123**
5. Dashboard opens

### Step 5: Package for Distribution

```bash
# Build macOS app
cd electron-app
npm run dist:mac
```

Output: `electron-app/release/Enterprise Monitor.dmg`

---

## 🔧 Development Workflow

### Running in Development Mode

**Terminal 1 - Backend:**
```bash
# Windows
cd backend-windows
venv\Scripts\activate
python main.py

# macOS
cd backend-macos
swift run
```

**Terminal 2 - Electron:**
```bash
cd electron-app
npm start
```

### Hot Reload Development

```bash
# Terminal 1: Backend (auto-restart on changes)
# Windows
cd backend-windows
pip install watchdog
watchmedo auto-restart --directory=. --pattern=*.py --recursive python main.py

# Terminal 2: Electron with hot reload
cd electron-app
npm run watch  # In one terminal
npm start      # In another terminal
```

---

## 🔐 Security Configuration

### ⚠️ IMPORTANT: Change Default Password

**Windows:**
Edit `backend-windows/auth/auth_manager.py`:
```python
# Line ~35
default_users = {
    "admin": self.pwd_context.hash("YOUR_SECURE_PASSWORD_HERE")
}
```

**macOS:**
Edit `backend-macos/Sources/main.swift`:
```swift
# Line ~55
if loginReq.username == "admin" && loginReq.password == "YOUR_SECURE_PASSWORD_HERE" {
```

**Or change via API after first run:**
```bash
# (Implement password change endpoint)
```

### JWT Secret Key

**Windows:**
Edit `backend-windows/auth/auth_manager.py`:
```python
# Line ~14
SECRET_KEY = "your-production-secret-key-min-32-chars"
```

### Database Encryption (Optional)

For sensitive data, consider using SQLCipher:
```bash
# Windows
pip install pysqlcipher3

# macOS
brew install sqlcipher
```

---

## 📊 Monitoring Features

### 1. Screenshot Capture
- **Interval:** Every 60 seconds (configurable)
- **Storage:** Local filesystem
- **Database:** Metadata only (path, timestamp, active window)

### 2. App Tracking
- **Tracks:** Active application name and window title
- **Interval:** Every 5 seconds
- **Purpose:** Productivity analytics

### 3. Clipboard Monitoring
- **Tracks:** Text copied to clipboard
- **Storage:** Preview only (100 chars)
- **Purpose:** Security audit

### 4. Server Synchronization (New)
- **Tracks:** Uploads local data to central server
- **Config:** Managed via `ConfigManager`
- **Endpoints:** `/api/config`

### 5. Automated Cleanup (New)
- **Action:** Deletes data older than 7 days
- **Schedule:** Runs every 24 hours

---

## 🎨 Customization

### Change Screenshot Interval

**Windows:** `backend-windows/monitoring/screenshot.py`
```python
# Line ~17
def __init__(self, db_manager, interval_seconds: int = 60):
    # Change to 300 for 5 minutes
    self.interval_seconds = 300
```

**macOS:** Similar pattern in Swift

### Change GUI Theme

Edit `electron-app/src/renderer/index.html`:
```css
/* Line ~16 - Change gradient */
background: linear-gradient(135deg, #your-color1 0%, #your-color2 100%);
```

### Add Company Logo

Replace icons in `electron-app/resources/`:
- `icon.icns` (macOS)
- `icon.ico` (Windows)
- `icon.png` (Linux)

---

## 🐛 Troubleshooting

### Backend Won't Start

**Windows:**
```cmd
# Check Python version
python --version  # Should be 3.11+

# Check if port is in use
netstat -ano | findstr :51235

# Kill process if needed
taskkill /PID <PID> /F
```

**macOS:**
```bash
# Check Swift version
swift --version

# Check port usage
lsof -i :51234

# Kill process
kill -9 <PID>
```

### Electron App Won't Open

```bash
# Clear Electron cache
# Windows
del /s /q %APPDATA%\enterprise-monitor\Cache

# Rebuild and Ensure Assets Copied
cd electron-app
rm -rf node_modules dist
npm install
npm run build
xcopy /E /I src\renderer\index.html dist\renderer\
npm start
```

### Screenshots Not Captured

**Windows:**
```cmd
# Ensure mss is installed
pip install mss pillow

# Test screenshot manually
python
>>> import mss
>>> with mss.mss() as sct:
>>>     sct.shot(output='test.png')
```

**macOS:**
- Grant Screen Recording permission
- System Preferences → Privacy & Security → Screen Recording
- Add Enterprise Monitor

### Database Errors

```bash
# Windows
del %LOCALAPPDATA%\EnterpriseMonitor\monitoring.db

# macOS
rm ~/Library/Application\ Support/EnterpriseMonitor/monitoring.db

# Restart backend (database will auto-recreate)
```

---

## 📦 Production Deployment

### Windows Installer

```cmd
cd electron-app
npm run dist:win
```

Creates: `Enterprise Monitor Setup.exe`

**Distribution:**
1. Share installer with employees
2. Run installer (admin rights required)
3. Backend installs as Windows Service
4. App auto-starts on login

### macOS App Bundle

```bash
cd electron-app
npm run dist:mac
```

Creates: `Enterprise Monitor.dmg`

**Distribution:**
1. Share .dmg file
2. Users drag app to Applications folder
3. Grant permissions when prompted
4. App auto-starts on login

### Auto-Start Configuration

**Windows Service:**
```cmd
# Install NSSM (Non-Sucking Service Manager)
# Download from: https://nssm.cc/download

nssm install EnterpriseMonitor "C:\Program Files\Enterprise Monitor\backend\python.exe" "C:\Program Files\Enterprise Monitor\backend\main.py"
nssm start EnterpriseMonitor
```

**macOS LaunchAgent:**
```bash
# Create launch agent plist
# See: backend-macos/LaunchAgent/com.company.enterprise-monitor.plist

# Install
cp com.company.enterprise-monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.company.enterprise-monitor.plist
```

---

## 🎁 Creating Windows Executable (Complete Guide)

> [!IMPORTANT]
> **Code Changes Required**: The current `main.ts` is configured for **development mode**. To build a standalone installer, you **MUST** apply the code changes described in [Step 2.2](#22-update-main-process-to-use-bundled-backend) below. These changes tell Electron to launch the bundled Python executable instead of expecting a separate backend process.

This section provides detailed instructions for creating a standalone Windows executable that bundles both the Electron app and Python backend.

### Prerequisites for Building

1. **Windows 10/11** (build machine)
2. **Python 3.11+** installed
3. **Node.js 18+** installed
4. **Visual Studio Build Tools** (for native modules)

### Step 1: Prepare Python Backend Executable

We'll use **PyInstaller** to bundle the Python backend into a standalone executable.

#### 1.1 Install PyInstaller

```cmd
cd backend-windows
venv\Scripts\activate
pip install pyinstaller
```

#### 1.2 Create PyInstaller Spec File

Create `backend-windows/enterprise-monitor-backend.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'passlib.handlers.bcrypt',
        'win32timezone',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='enterprise-monitor-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False to hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../electron-app/resources/icon.ico'
)
```

#### 1.3 Build Backend Executable

```cmd
cd backend-windows
venv\Scripts\activate
pyinstaller enterprise-monitor-backend.spec
```

Output: `backend-windows/dist/enterprise-monitor-backend.exe`

#### 1.4 Test Backend Executable

```cmd
cd backend-windows\dist
enterprise-monitor-backend.exe
```

Verify it starts on `http://127.0.0.1:51235`

### Step 2: Configure Electron Builder

#### 2.1 Update package.json

The `electron-app/package.json` already has electron-builder configuration. Verify these settings:

```json
{
  "build": {
    "appId": "com.company.enterprise-monitor",
    "productName": "Enterprise Monitor",
    "directories": {
      "output": "release"
    },
    "files": [
      "dist/**/*",
      "resources/**/*",
      "package.json"
    ],
    "extraResources": [
      {
        "from": "../backend-windows/dist/enterprise-monitor-backend.exe",
        "to": "backend/enterprise-monitor-backend.exe"
      }
    ],
    "win": {
      "target": ["nsis"],
      "icon": "resources/icon.ico"
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "createDesktopShortcut": false,
      "createStartMenuShortcut": true,
      "installerIcon": "resources/icon.ico",
      "uninstallerIcon": "resources/icon.ico",
      "installerHeaderIcon": "resources/icon.ico",
      "runAfterFinish": true
    }
  }
}
```

#### 2.2 Update Main Process to Use Bundled Backend

Edit `electron-app/src/main/main.ts` to start the bundled backend:

Add at the top:
```typescript
import { spawn } from 'child_process';
import * as path from 'path';

let backendProcess: any = null;

function startBackend() {
  const isDev = !app.isPackaged;
  
  if (isDev) {
    // Development: assume backend is running separately
    console.log('Development mode: expecting backend on port 51235');
    return;
  }
  
  // Production: start bundled backend
  const backendPath = path.join(
    process.resourcesPath,
    'backend',
    'enterprise-monitor-backend.exe'
  );
  
  console.log('Starting backend from:', backendPath);
  
  backendProcess = spawn(backendPath, [], {
    detached: false,
    stdio: 'ignore'
  });
  
  backendProcess.on('error', (err: Error) => {
    console.error('Backend failed to start:', err);
  });
}

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});
```

Then call `startBackend()` in the `app.whenReady()` block:

```typescript
app.whenReady().then(async () => {
  startBackend(); // Add this line
  
  app.setLoginItemSettings({
    openAtLogin: true,
    path: app.getPath('exe')
  });
  
  // ... rest of the code
});
```

### Step 3: Build Complete Installer

#### 3.1 Full Build Process

```cmd
# 1. Build Python backend
cd backend-windows
venv\Scripts\activate
pyinstaller enterprise-monitor-backend.spec
cd ..

# 2. Build Electron app with bundled backend
cd electron-app
npm install
npm run build
npm run dist:win
```

#### 3.2 Output Location

The installer will be created at:
```
electron-app/release/Enterprise Monitor Setup 1.0.0.exe
```

### Step 4: Test the Installer

1. **Copy installer to clean Windows machine** (or VM)
2. **Run installer** (may require admin rights)
3. **Installation location**: `C:\Users\{Username}\AppData\Local\Programs\enterprise-monitor\`
4. **Backend location**: `C:\Users\{Username}\AppData\Local\Programs\enterprise-monitor\resources\backend\`
5. **Launch app** from Start Menu
6. **Verify**:
   - App appears in system tray
   - Backend starts automatically
   - Login works
   - Monitoring services start

### Step 5: Distribution

#### 5.1 Internal Distribution

**Option A: Network Share**
```cmd
# Copy installer to network share
copy "electron-app\release\Enterprise Monitor Setup 1.0.0.exe" "\\server\share\installers\"

# Notify employees via email with installation instructions
```

**Option B: Download Portal**
- Upload to company intranet
- Provide download link
- Include installation guide

#### 5.2 Silent Installation (for IT deployment)

```cmd
# Silent install for all users
"Enterprise Monitor Setup 1.0.0.exe" /S /allusers

# Silent install for current user
"Enterprise Monitor Setup 1.0.0.exe" /S /currentuser
```

#### 5.3 Group Policy Deployment

1. **Create MSI** (requires additional tools like Advanced Installer)
2. **Deploy via GPO**:
   - Computer Configuration → Policies → Software Settings → Software Installation
   - Add package
   - Assign to computers

### Step 6: Auto-Update Configuration (Future)

To implement auto-updates using electron-updater:

#### 6.1 Install electron-updater

```cmd
cd electron-app
npm install electron-updater
```

#### 6.2 Configure Update Server

Update `package.json`:
```json
{
  "build": {
    "publish": {
      "provider": "generic",
      "url": "https://your-server.com/updates/"
    }
  }
}
```

#### 6.3 Add Update Logic

In `main.ts`:
```typescript
import { autoUpdater } from 'electron-updater';

app.whenReady().then(() => {
  autoUpdater.checkForUpdatesAndNotify();
});
```

### Troubleshooting Build Issues

#### Issue: PyInstaller Missing Modules

**Solution**: Add to `hiddenimports` in spec file
```python
hiddenimports=[
    'your_missing_module',
]
```

#### Issue: Backend Doesn't Start

**Solution**: Check logs
```
%LOCALAPPDATA%\Programs\enterprise-monitor\resources\backend\backend.log
```

#### Issue: Large Installer Size

**Solution**: Exclude unnecessary files
```json
{
  "build": {
    "files": [
      "!**/*.map",
      "!**/*.md",
      "!**/node_modules/*/{CHANGELOG.md,README.md,README,readme.md,readme}"
    ]
  }
}
```

#### Issue: Antivirus Flags Executable

**Solution**: Code signing
```cmd
# Obtain code signing certificate
# Sign executable
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com "Enterprise Monitor Setup.exe"
```

---

## 📈 Scaling & Performance

### Database Cleanup

Run periodic cleanup (built-in):
```python
# Keeps last 7 days by default
db_manager.cleanup_old_data(days=7)
```

### Screenshot Storage

Monitor disk usage:
```bash
# Windows
dir "%LOCALAPPDATA%\EnterpriseMonitor\screenshots"

# macOS
du -sh ~/Library/Application\ Support/EnterpriseMonitor/screenshots
```

### Central Server Sync (Future)

To implement centralized logging:
1. Setup REST API server
2. Modify `api_server.py` to POST data periodically
3. Use JWT for authentication
4. Implement HTTPS for security

---

## 🔒 Privacy & Legal

### Employee Notification

**IMPORTANT:** Inform employees about monitoring:
- Add notification on first login
- Include in employment agreement
- Display monitoring status in system tray

### Data Retention

Default: 7 days local storage

Compliance requirements:
- GDPR: User right to access/delete data
- CCPA: Disclosure of monitoring
- Local laws: Vary by jurisdiction

### Recommended Practices

1. ✅ Clear privacy policy
2. ✅ Employee consent
3. ✅ Limited data retention
4. ✅ Secure data storage
5. ✅ Admin-only access
6. ✅ Audit logging

---

## 🚀 Next Steps

### Phase 1: Basic Deployment (Week 1)
- [ ] Setup development environment
- [ ] Test all features locally
- [ ] Change default credentials
- [ ] Create installer packages

### Phase 2: Production Rollout (Week 2)
- [ ] Deploy to pilot group (5-10 users)
- [ ] Gather feedback
- [ ] Fix issues
- [ ] Document procedures

### Phase 3: Full Deployment (Week 3)
- [ ] Roll out company-wide
- [ ] Setup central server (optional)
- [ ] Monitor system health
- [ ] Provide user support

---

## 🔮 Future Development Guidance

This section provides guidance for extending and enhancing the Enterprise Monitor system.

### Feature Enhancements

#### 1. **Advanced Analytics Dashboard**

**Goal**: Add productivity insights, trends, and AI-powered recommendations

**Implementation Steps**:
1. **Add new database tables**:
   ```sql
   CREATE TABLE productivity_scores (
       id INTEGER PRIMARY KEY,
       date TEXT,
       user_id TEXT,
       productivity_score REAL,
       focus_time_minutes INTEGER,
       distraction_count INTEGER
   );
   ```

2. **Create analytics service** (`backend-windows/analytics/`):
   ```python
   # analytics_engine.py
   class ProductivityAnalyzer:
       def calculate_daily_score(self, user_id, date):
           # Analyze app usage patterns
           # Calculate focus time vs. distraction time
           # Return productivity score (0-100)
           pass
   ```

3. **Add API endpoints**:
   ```python
   @app.get("/api/analytics/productivity")
   async def get_productivity_analytics(date: str):
       # Return productivity trends, insights
       pass
   ```

4. **Update frontend**: Add new charts using Chart.js

#### 2. **Multi-User Support**

**Goal**: Support multiple users per machine with individual tracking

**Implementation Steps**:
1. **Modify database schema**:
   ```sql
   ALTER TABLE screenshots ADD COLUMN user_id TEXT;
   ALTER TABLE app_activity ADD COLUMN user_id TEXT;
   ```

2. **Add user detection**:
   ```python
   import getpass
   current_user = getpass.getuser()
   ```

3. **Update all monitoring services** to include `user_id`

4. **Add user management UI** in dashboard

#### 3. **Webcam Capture (Optional)**

**Goal**: Periodic webcam snapshots for enhanced monitoring

**Implementation Steps**:
1. **Install OpenCV**:
   ```cmd
   pip install opencv-python
   ```

2. **Create webcam service** (`monitoring/webcam.py`):
   ```python
   import cv2
   
   class WebcamMonitor:
       def capture_image(self):
           cap = cv2.VideoCapture(0)
           ret, frame = cap.read()
           if ret:
               cv2.imwrite('webcam.jpg', frame)
           cap.release()
   ```

3. **Add privacy controls**: Allow users to disable webcam monitoring

#### 4. **Keystroke Logging (Use with Caution)**

**Goal**: Track keyboard activity for detailed productivity analysis

**⚠️ Legal Warning**: Keystroke logging may be illegal in many jurisdictions. Consult legal counsel before implementing.

**Implementation Steps**:
1. **Install pynput**:
   ```cmd
   pip install pynput
   ```

2. **Create keyboard monitor** (`monitoring/keyboard.py`):
   ```python
   from pynput import keyboard
   
   class KeyboardMonitor:
       def on_press(self, key):
           # Log key press (anonymized)
           # Track typing speed, activity patterns
           pass
   ```

3. **Store aggregated data only** (not actual keystrokes for privacy)

#### 5. **Email/Slack Notifications**

**Goal**: Alert admins of suspicious activity or policy violations

**Implementation Steps**:
1. **Install notification libraries**:
   ```cmd
   pip install sendgrid slack-sdk
   ```

2. **Create notification service** (`services/notification_service.py`):
   ```python
   class NotificationService:
       def send_alert(self, message, severity):
           # Send email via SendGrid
           # Send Slack message
           pass
   ```

3. **Define alert rules**:
   - Excessive idle time
   - Blocked application usage
   - Unusual activity patterns

#### 6. **Mobile App (iOS/Android)**

**Goal**: Admin dashboard on mobile devices

**Technology Stack**:
- **React Native** or **Flutter**
- **REST API** (already available)

**Features**:
- View real-time statistics
- Browse screenshots
- Pause/resume monitoring
- Receive push notifications

### Scalability Improvements

#### 1. **PostgreSQL Migration**

**Goal**: Replace SQLite with PostgreSQL for better performance at scale

**Steps**:
1. **Install PostgreSQL**:
   ```cmd
   pip install psycopg2-binary
   ```

2. **Update `db_manager.py`**:
   ```python
   import psycopg2
   
   conn = psycopg2.connect(
       host="localhost",
       database="enterprise_monitor",
       user="admin",
       password="password"
   )
   ```

3. **Migrate data**: Use `pg_dump` and custom migration scripts

#### 2. **Redis Caching**

**Goal**: Cache frequently accessed data for faster API responses

**Steps**:
1. **Install Redis**:
   ```cmd
   pip install redis
   ```

2. **Add caching layer**:
   ```python
   import redis
   
   cache = redis.Redis(host='localhost', port=6379)
   
   @app.get("/api/statistics")
   async def get_statistics():
       cached = cache.get('stats:today')
       if cached:
           return json.loads(cached)
       
       stats = db_manager.get_statistics()
       cache.setex('stats:today', 300, json.dumps(stats))
       return stats
   ```

#### 3. **Microservices Architecture**

**Goal**: Split monolithic backend into microservices

**Services**:
- **Auth Service**: User authentication, JWT management
- **Monitoring Service**: Screenshot, app tracking, clipboard
- **Analytics Service**: Data processing, reporting
- **Sync Service**: ERP synchronization
- **API Gateway**: Route requests to appropriate service

**Technology**: Docker, Kubernetes, RabbitMQ/Kafka

### Security Enhancements

#### 1. **End-to-End Encryption**

**Goal**: Encrypt screenshots and sensitive data

**Steps**:
1. **Install cryptography**:
   ```cmd
   pip install cryptography
   ```

2. **Encrypt screenshots**:
   ```python
   from cryptography.fernet import Fernet
   
   key = Fernet.generate_key()
   cipher = Fernet(key)
   
   with open('screenshot.jpg', 'rb') as f:
       encrypted = cipher.encrypt(f.read())
   ```

3. **Store encryption keys** in secure key management system (e.g., Azure Key Vault)

#### 2. **Role-Based Access Control (RBAC)**

**Goal**: Different permission levels (Admin, Manager, Viewer)

**Steps**:
1. **Add roles table**:
   ```sql
   CREATE TABLE users (
       id INTEGER PRIMARY KEY,
       username TEXT,
       password_hash TEXT,
       role TEXT  -- 'admin', 'manager', 'viewer'
   );
   ```

2. **Update auth middleware**:
   ```python
   def require_role(required_role):
       def decorator(func):
           async def wrapper(*args, user=Depends(verify_token), **kwargs):
               if user['role'] != required_role:
                   raise HTTPException(403, "Insufficient permissions")
               return await func(*args, **kwargs)
           return wrapper
       return decorator
   
   @app.delete("/api/data/delete")
   @require_role('admin')
   async def delete_data():
       pass
   ```

#### 3. **Two-Factor Authentication (2FA)**

**Goal**: Add TOTP-based 2FA for admin login

**Steps**:
1. **Install pyotp**:
   ```cmd
   pip install pyotp qrcode
   ```

2. **Generate TOTP secret**:
   ```python
   import pyotp
   
   secret = pyotp.random_base32()
   totp = pyotp.TOTP(secret)
   ```

3. **Verify 2FA code** during login

### Integration Possibilities

#### 1. **Active Directory Integration**

**Goal**: Use corporate AD credentials for authentication

**Steps**:
1. **Install ldap3**:
   ```cmd
   pip install ldap3
   ```

2. **Update auth_manager.py**:
   ```python
   from ldap3 import Server, Connection
   
   def verify_ad_credentials(username, password):
       server = Server('ldap://your-ad-server.com')
       conn = Connection(server, user=f'{username}@domain.com', password=password)
       return conn.bind()
   ```

#### 2. **SIEM Integration**

**Goal**: Send logs to Security Information and Event Management systems

**Supported SIEM**:
- Splunk
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Azure Sentinel

**Steps**:
1. **Install logging handler**:
   ```cmd
   pip install splunk-sdk
   ```

2. **Configure log forwarding**:
   ```python
   import logging
   from splunk_handler import SplunkHandler
   
   splunk = SplunkHandler(
       host='splunk.company.com',
       port=8088,
       token='YOUR_TOKEN'
   )
   logger.addHandler(splunk)
   ```

#### 3. **HR System Integration**

**Goal**: Sync employee data, work schedules, time-off

**Steps**:
1. **Connect to HR API** (e.g., BambooHR, Workday)
2. **Sync employee roster**
3. **Exclude monitoring during time-off**
4. **Generate attendance reports**

### Performance Optimization

#### 1. **Screenshot Compression Improvements**

**Current**: JPEG compression with quality adjustment  
**Enhancement**: Use WebP format for better compression

```python
from PIL import Image

img.save('screenshot.webp', 'WEBP', quality=80, method=6)
```

#### 2. **Async Database Operations**

**Goal**: Use async SQLite for non-blocking I/O

**Steps**:
1. **Install aiosqlite**:
   ```cmd
   pip install aiosqlite
   ```

2. **Update db_manager.py**:
   ```python
   import aiosqlite
   
   async def insert_screenshot(self, file_path, active_window, active_app):
       async with aiosqlite.connect(self.db_path) as conn:
           await conn.execute(
               "INSERT INTO screenshots (...) VALUES (...)",
               (file_path, active_window, active_app)
           )
           await conn.commit()
   ```

#### 3. **Background Job Queue**

**Goal**: Offload heavy tasks (screenshot processing, sync) to background workers

**Technology**: Celery + Redis

**Steps**:
1. **Install Celery**:
   ```cmd
   pip install celery redis
   ```

2. **Create tasks**:
   ```python
   from celery import Celery
   
   app = Celery('tasks', broker='redis://localhost:6379')
   
   @app.task
   def process_screenshot(file_path):
       # Compress, analyze, upload
       pass
   ```

### Compliance & Privacy

#### 1. **GDPR Compliance**

**Requirements**:
- User consent mechanism
- Data export functionality
- Right to be forgotten (data deletion)
- Data retention policies

**Implementation**:
```python
@app.get("/api/gdpr/export")
async def export_user_data(user_id: str):
    # Export all user data as JSON
    pass

@app.delete("/api/gdpr/delete")
async def delete_user_data(user_id: str):
    # Delete all user data
    pass
```

#### 2. **Audit Logging**

**Goal**: Track all admin actions for compliance

**Steps**:
1. **Create audit log table**:
   ```sql
   CREATE TABLE audit_log (
       id INTEGER PRIMARY KEY,
       timestamp TEXT,
       user_id TEXT,
       action TEXT,
       resource TEXT,
       details TEXT
   );
   ```

2. **Log all sensitive operations**:
   ```python
   def log_audit(user_id, action, resource, details):
       db.execute(
           "INSERT INTO audit_log (...) VALUES (...)",
           (datetime.utcnow().isoformat(), user_id, action, resource, details)
       )
   ```

### Testing & Quality Assurance

#### 1. **Unit Tests**

**Framework**: pytest

```cmd
pip install pytest pytest-asyncio
```

**Example test** (`tests/test_db_manager.py`):
```python
import pytest
from database.db_manager import DatabaseManager

def test_insert_screenshot():
    db = DatabaseManager()
    db.insert_screenshot('/path/to/screenshot.jpg', 'Window Title', 'app.exe')
    screenshots = db.get_screenshots(limit=1)
    assert len(screenshots) == 1
```

#### 2. **Integration Tests**

**Test API endpoints**:
```python
from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)

def test_login():
    response = client.post('/api/auth/login', json={
        'username': 'admin',
        'password': 'admin123'
    })
    assert response.status_code == 200
    assert 'token' in response.json()
```

#### 3. **Load Testing**

**Tool**: Locust

```cmd
pip install locust
```

**Load test script** (`locustfile.py`):
```python
from locust import HttpUser, task

class MonitorUser(HttpUser):
    @task
    def get_statistics(self):
        self.client.get('/api/statistics')
```

Run: `locust -f locustfile.py`

### Deployment Automation

#### 1. **CI/CD Pipeline**

**Platform**: GitHub Actions, GitLab CI, or Jenkins

**Example GitHub Actions** (`.github/workflows/build.yml`):
```yaml
name: Build and Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Build Backend
        run: |
          cd backend-windows
          pip install -r requirements.txt
          pip install pyinstaller
          pyinstaller enterprise-monitor-backend.spec
      - name: Setup Node
        uses: actions/setup-node@v2
        with:
          node-version: '18'
      - name: Build Electron App
        run: |
          cd electron-app
          npm install
          npm run build
          npm run dist:win
      - name: Upload Release
        uses: actions/upload-artifact@v2
        with:
          name: installer
          path: electron-app/release/*.exe
```

#### 2. **Automated Testing**

Add to CI/CD pipeline:
```yaml
- name: Run Tests
  run: |
    cd backend-windows
    pytest tests/
```

### Documentation

#### 1. **API Documentation**

FastAPI auto-generates docs at `/docs` (Swagger UI)

**Enhance with**:
- Detailed descriptions
- Example requests/responses
- Authentication instructions

#### 2. **User Manual**

**Create PDF guide** covering:
- Installation steps
- Dashboard usage
- Privacy policy
- FAQ
- Troubleshooting

**Tool**: Markdown → PDF using Pandoc

```cmd
pandoc USER_MANUAL.md -o USER_MANUAL.pdf
```

#### 3. **Developer Documentation**

**Topics**:
- Architecture overview
- Database schema
- API reference
- Code style guide
- Contributing guidelines

**Host on**: GitHub Wiki, GitBook, or internal wiki

---

## 📞 Support

### Getting Help

1. **Check logs:**
   - Windows: `%LOCALAPPDATA%\EnterpriseMonitor\logs\`
   - macOS: `/tmp/enterprise-monitor.log`

2. **Common issues:** See Troubleshooting section above

3. **API debugging:**
   ```bash
   # Test health endpoint
   curl http://localhost:51234/health
   
   # Test login
   curl -X POST http://localhost:51234/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"Admin@123"}'
   ```

### System Requirements

**Minimum:**
- Windows 10/11 or macOS 13+
- 4GB RAM
- 500MB disk space
- Internet for initial setup

**Recommended:**
- 8GB RAM
- SSD storage
- Gigabit network (if using central server)

---

## ✅ Production Checklist

Before deploying:

- [ ] Changed default admin password
- [ ] Changed JWT secret key
- [ ] Tested on clean Windows machine
- [ ] Tested on clean macOS machine
- [ ] Verified screenshot capture works
- [ ] Verified admin login works
- [ ] Tested monitoring pause/resume
- [ ] Configured auto-start
- [ ] Created user documentation
- [ ] Notified employees about monitoring
- [ ] Setup data retention policy
- [ ] Implemented logging and monitoring
- [ ] Created backup procedures

---

## 📄 License

**PROPRIETARY** - Internal use only

---

**Built with:**
- Electron (GUI)
- TypeScript (Frontend)
- Python + FastAPI (Windows Backend)
- Swift + Vapor (macOS Backend)
- SQLite (Database)

**Version:** 1.0.0
**Last Updated:** February 2026
