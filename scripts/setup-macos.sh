#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Enterprise Monitor — macOS Backend Builder
# ═══════════════════════════════════════════════════════════════════════════════
#
# Installs dependencies directly into system Python and builds the backend
# binary via PyInstaller.
#
# Usage:
#   cd <project-root>
#   chmod +x scripts/setup-macos.sh
#   ./scripts/setup-macos.sh
#
# Output:
#   backend-macos/dist/enterprise_monitor_backend/
#     └── enterprise_monitor_backend   ← standalone executable
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

# Python 3.9+
if ! command -v python3 &> /dev/null; then
    echo ""
    echo "[ERROR] Python 3 not found!"
    echo "  Install via Homebrew:  brew install python@3.11"
    echo "  Or download from:     https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo "[ERROR] Python 3.9+ required. Found: $PYTHON_VERSION"
    exit 1
fi
echo "  [OK] Python $PYTHON_VERSION ($(which python3))"

# Node.js (for Electron)
if ! command -v node &> /dev/null; then
    echo ""
    echo "[ERROR] Node.js not found!"
    echo "  Install via Homebrew:  brew install node"
    echo "  Or download from:     https://nodejs.org/"
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  [OK] Node.js $NODE_VERSION"

# ── STEP 1: Install Python Dependencies ─────────────────────────────────────

echo ""
echo "[1/4] Installing Python dependencies (system-wide)..."

pip3 install -r "$BACKEND_DIR/requirements.txt"
echo "  [OK] All dependencies installed"

# ── STEP 2: Build Backend with PyInstaller ──────────────────────────────────

echo ""
echo "[2/4] Building backend with PyInstaller (onedir, arm64)..."

cd "$BACKEND_DIR"

# Clean previous build artifacts
if [ -d "$BACKEND_DIR/build" ]; then
    echo "  Cleaning previous build..."
    rm -rf "$BACKEND_DIR/build"
fi
if [ -d "$DIST_DIR" ]; then
    echo "  Cleaning previous dist..."
    rm -rf "$DIST_DIR"
fi

# Build using the .spec file if it exists, otherwise fall back to inline flags
if [ -f "enterprise_monitor_backend_mac.spec" ]; then
    echo "  Using enterprise_monitor_backend_mac.spec"
    python3 -m PyInstaller enterprise_monitor_backend_mac.spec --noconfirm
else
    echo "  No .spec file found — using inline flags"
    python3 -m PyInstaller \
        --onedir \
        --name enterprise_monitor_backend \
        --console \
        --noconfirm \
        --hidden-import=uvicorn.logging \
        --hidden-import=uvicorn.loops \
        --hidden-import=uvicorn.loops.auto \
        --hidden-import=uvicorn.protocols \
        --hidden-import=uvicorn.protocols.http \
        --hidden-import=uvicorn.protocols.http.auto \
        --hidden-import=uvicorn.protocols.websockets \
        --hidden-import=uvicorn.protocols.websockets.auto \
        --hidden-import=uvicorn.lifespan \
        --hidden-import=uvicorn.lifespan.on \
        --hidden-import=anyio \
        --hidden-import=anyio.backends.asyncio \
        --hidden-import='anyio._backends._asyncio' \
        --hidden-import=multipart \
        --hidden-import=pynput.keyboard._darwin \
        --hidden-import=pynput.mouse._darwin \
        --hidden-import=Quartz \
        --hidden-import=ApplicationServices \
        --hidden-import=jose \
        --hidden-import=jose.jwt \
        --hidden-import=jose.backends \
        --hidden-import=numpy.core._methods \
        --hidden-import=numpy.lib.format \
        --hidden-import=cv2 \
        --collect-all=cv2 \
        --collect-all=mss \
        --collect-all=pynput \
        --noupx \
        main.py
fi

# Verify the build output exists
if [ ! -d "$DIST_DIR" ]; then
    echo ""
    echo "[ERROR] Build failed — dist directory not found: $DIST_DIR"
    echo "  Check the PyInstaller output above for errors."
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
npm run build
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
echo "    1. Start the backend:"
echo "       cd backend-macos"
echo "       python3 main.py"
echo ""
echo "    2. Start Electron (new terminal):"
echo "       cd electron-app"
echo "       npm start"
echo ""
echo "  To build the final installer:"
echo "    cd electron-app"
echo "    npm run dist"
echo ""
echo "  Default login: admin / Admin@123"
echo ""
echo "  IMPORTANT: Grant these permissions when prompted:"
echo "    • Screen Recording   (System Settings → Privacy → Screen Recording)"
echo "    • Accessibility      (System Settings → Privacy → Accessibility)"
echo "    • Input Monitoring    (System Settings → Privacy → Input Monitoring)"
echo ""
