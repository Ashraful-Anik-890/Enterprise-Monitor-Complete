# Enterprise Monitor

**Professional Employee Monitoring System**

Cross-platform monitoring solution built with Electron, Python, and Swift.

---

## 🚀 Quick Start

### Windows
```cmd
:: Backend Setup
cd backend-windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
:: Note: Default port is 51235
python main.py

:: New terminal - Frontend Setup
cd electron-app
npm install
:: Build and copy assets (Important!)
npm run build
xcopy /E /I src\renderer\index.html dist\renderer\
npm start
```

### macOS
```bash
cd backend-macos
swift build
swift run

# New terminal
cd electron-app
npm install
npm run build
npm start
```

---

## 📚 Full Documentation

See **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** for complete setup instructions, troubleshooting, and deployment guide.

---

## 🏗️ Architecture

```
┌─────────────────────────────────┐
│   Electron GUI (TypeScript)     │
│   Cross-platform                │
└────────────┬────────────────────┘
             │ HTTP REST API (51235)
┌────────────┴────────────────────┐
│   Backend Services              │
│   • Windows: Python + FastAPI   │
│   • macOS: Swift + Vapor        │
│   • Sync Service -> Cloud API   │
└─────────────────────────────────┘
```

---

## ✨ Features

- ✅ Screenshot capture (60s intervals)
- ✅ Application tracking & Statistics
- ✅ Clipboard monitoring
- ✅ **Central Server Synchronization** (New)
- ✅ **Remote Configuration API** (New)
- ✅ **Automated Data Cleanup** (7-day retention)
- ✅ Admin authentication (JWT)
- ✅ Cross-platform (Windows + macOS)
- ✅ System tray integration

---

## 🔐 Default Credentials

**Username:** admin  
**Password:** admin123

**⚠️ CHANGE IMMEDIATELY IN PRODUCTION!**

---

## 📦 What's Included

- `electron-app/` - Cross-platform GUI
- `backend-windows/` - Python backend for Windows
- `backend-macos/` - Swift backend for macOS
- `IMPLEMENTATION_GUIDE.md` - Complete documentation

---

## 🛠️ Tech Stack

**Frontend:**
- Electron 28.x
- TypeScript 5.x
- Modern HTML/CSS

**Backend (Windows):**
- Python 3.11+
- FastAPI
- SQLite

**Backend (macOS):**
- Swift 5.9+
- Vapor
- SQLite

---

## 📋 Requirements

**Windows:**
- Python 3.11+
- Node.js 18+
- Windows 10/11

**macOS:**
- Swift 5.9+
- Node.js 18+
- macOS 13+

---

## 🚨 Important Notes

1. **Privacy:** Inform employees about monitoring
2. **Security:** Change default credentials
3. **Legal:** Ensure compliance with local laws
4. **Permissions:** Grant required macOS permissions

---

## 📞 Support

Check logs:
- Windows: `%LOCALAPPDATA%\EnterpriseMonitor\logs\`
- macOS: `/tmp/enterprise-monitor.log`

Test backend:
```bash
curl http://localhost:51235/health
```

---

## 📄 License

PROPRIETARY - Internal use only

---

**Version:** 1.0.0  
**Author:** Enterprise IT Team
