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
