#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Enterprise Monitor — macOS Backend Builder
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend-macos"
ELECTRON_DIR="$PROJECT_ROOT/electron-app"
DIST_DIR="$BACKEND_DIR/dist/enterprise_monitor_backend"

echo ""
echo "========================================================"
echo "  Enterprise Monitor — macOS Setup & Build"
echo "========================================================"
echo ""

# ── STEP 0: Prerequisites ────────────────────────────────────────────────────

echo "[0/4] Checking prerequisites..."

# Prefer Homebrew python3.12 since the system python3 (3.9) on macOS
# does not have project dependencies (passlib, bcrypt, etc.) installed.
# PyInstaller MUST run under the same Python that has all packages installed,
# otherwise hidden-imports like passlib.handlers.bcrypt are silently missing
# from the bundle, causing CRITICAL startup failures at runtime.
PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        # Verify this Python can import passlib (our key dependency)
        if "$candidate" -c "import passlib.handlers.bcrypt" &>/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Could not find a Python 3 installation with passlib installed."
    echo "  Fix: /opt/homebrew/bin/python3.12 -m pip install -r backend-macos/requirements.txt"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo "[ERROR] Python 3.9+ required. Found: $PYTHON_VERSION"
    exit 1
fi
echo "  [OK] Python $PYTHON_VERSION ($PYTHON_BIN)"

if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found. Install: brew install node"
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  [OK] Node.js $NODE_VERSION"

# ── STEP 1: Install Python Dependencies ─────────────────────────────────────

echo ""
echo "[1/4] Installing Python dependencies..."
"$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements.txt"
echo "  [OK] All dependencies installed"

# ── STEP 2: Build Backend with PyInstaller ──────────────────────────────────

echo ""
echo "[2/4] Building backend with PyInstaller (onedir, arm64)..."

cd "$BACKEND_DIR"

if [ -d "$BACKEND_DIR/build" ]; then
    echo "  Cleaning previous build..."
    rm -rf "$BACKEND_DIR/build"
fi
if [ -d "$DIST_DIR" ]; then
    echo "  Cleaning previous dist..."
    rm -rf "$DIST_DIR"
fi

if [ -f "enterprise_monitor_backend_mac.spec" ]; then
    echo "  Using enterprise_monitor_backend_mac.spec"
    "$PYTHON_BIN" -m PyInstaller enterprise_monitor_backend_mac.spec --noconfirm
else
    echo "  [ERROR] enterprise_monitor_backend_mac.spec not found"
    exit 1
fi

if [ ! -d "$DIST_DIR" ]; then
    echo ""
    echo "[ERROR] Build failed — dist directory not found: $DIST_DIR"
    echo "  Common fixes:"
    echo "    Missing package:  pip3 install <package-name>"
    echo "    Stale cache:      rm -rf build/ dist/ and retry"
    exit 1
fi

echo "  [OK] Backend built: $DIST_DIR"

# ── STEP 3: Electron App ────────────────────────────────────────────────────

echo ""
echo "[3/4] Installing Electron dependencies..."
cd "$ELECTRON_DIR"
npm install
echo "  [OK] npm install complete"

echo ""
echo "[4/4] Building TypeScript..."
# FIX: use build:mac — NOT build (build uses xcopy, a Windows-only command)
npm run build:mac
echo "  [OK] TypeScript build complete"

# ── DONE ────────────────────────────────────────────────────────────────────

echo ""
echo "========================================================"
echo "  BUILD COMPLETE"
echo "========================================================"
echo ""
echo "  Backend binary:  $DIST_DIR"
echo ""
echo "  To run in development:"
echo ""
echo "    1. Start the backend:
       cd backend-macos && $PYTHON_BIN main.py
       # or using the Homebrew Python: $PYTHON_BIN main.py
"
echo ""
echo "    2. Start Electron (new terminal):"
echo "       cd electron-app && npm start"
echo ""
echo "  To build the DMG installer:"
echo "    cd electron-app && npm run dist:mac"
echo ""
echo "  Default login: admin / Admin@123"
echo ""
echo "  IMPORTANT: Grant permissions when prompted:"
echo "    • Screen Recording  — System Settings → Privacy → Screen Recording"
echo "    • Accessibility     — System Settings → Privacy → Accessibility"
echo "    • Input Monitoring  — System Settings → Privacy → Input Monitoring"
echo ""