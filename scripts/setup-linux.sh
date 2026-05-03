#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Enterprise Monitor — Linux Backend Builder
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend-linux"
ELECTRON_DIR="$PROJECT_ROOT/electron-app"
DIST_DIR="$BACKEND_DIR/dist/enterprise_monitor_backend"

echo ""
echo "========================================================"
echo "  Enterprise Monitor — Linux Setup & Build"
echo "========================================================"
echo ""

# ── STEP 0: Prerequisites ────────────────────────────────────────────────────

echo "[0/4] Checking prerequisites..."

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Could not find a Python 3 installation."
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  [OK] Python $PYTHON_VERSION ($PYTHON_BIN)"

if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found. Please install node."
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  [OK] Node.js $NODE_VERSION"

# ── STEP 1: Install Python Dependencies ─────────────────────────────────────

echo ""
echo "[1/4] Installing Python dependencies (via venv)..."
cd "$BACKEND_DIR"
if [ ! -d "venv" ]; then
    "$PYTHON_BIN" -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
echo "  [OK] All dependencies installed"

# ── STEP 2: Build Backend with PyInstaller ──────────────────────────────────

echo ""
echo "[2/4] Building backend with PyInstaller..."

if [ -d "build" ]; then
    echo "  Cleaning previous build..."
    rm -rf build
fi
if [ -d "$DIST_DIR" ]; then
    echo "  Cleaning previous dist..."
    rm -rf "$DIST_DIR"
fi

if [ -f "enterprise_monitor_backend.spec" ]; then
    echo "  Using enterprise_monitor_backend.spec"
    pyinstaller enterprise_monitor_backend.spec --noconfirm
else
    echo "  [ERROR] enterprise_monitor_backend.spec not found"
    exit 1
fi

if [ ! -d "$DIST_DIR" ]; then
    echo ""
    echo "[ERROR] Build failed — dist directory not found: $DIST_DIR"
    exit 1
fi

echo "  [OK] Backend built: $DIST_DIR"
deactivate

# ── STEP 3: Electron App ────────────────────────────────────────────────────

echo ""
echo "[3/4] Installing Electron dependencies..."
cd "$ELECTRON_DIR"
npm install
echo "  [OK] npm install complete"

echo ""
echo "[4/4] Building TypeScript..."
npm run build:linux
echo "  [OK] TypeScript build complete"

# ── DONE ────────────────────────────────────────────────────────────────────

echo ""
echo "========================================================"
echo "  BUILD COMPLETE"
echo "========================================================"
echo ""
echo "  To run in development:"
echo "    cd electron-app && npm run start:linux"
echo ""
echo "  To build the AppImage / deb installers:"
echo "    cd electron-app && npm run dist:linux"
echo ""
echo "  Default login: admin / Admin@123"
echo ""
