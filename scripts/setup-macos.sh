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

# ── STEP 1: Clean build environment ──────────────────────────────────────────

echo "[1/4] Cleaning build environment..."

# Clean backend artifacts
cd "$BACKEND_DIR"
rm -rf dist build dist_obf __pycache__ .pyarmor
echo "  [OK] Backend build folders cleared"

echo "  [OK] Workspace is clean"

# ── STEP 1a: Dependencies ───────────────────────────────────────────────────

echo ""
echo "[1a/4] Installing Python dependencies..."
cd "$BACKEND_DIR"
"$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements.txt"
echo "  [OK] All dependencies installed"

# ── STEP 1b: Obfuscate with PyArmor ─────────────────────────────────────────

echo ""
echo "[1b/4] Obfuscating Python source with PyArmor..."

cd "$BACKEND_DIR"

# Clean previous
rm -rf dist_obf
mkdir -p dist_obf

# Detect PyArmor module name
PYARMOR_MODULE=""
if "$PYTHON_BIN" -m pyarmor.cli --version >/dev/null 2>&1; then
    PYARMOR_MODULE="pyarmor.cli"
elif "$PYTHON_BIN" -m pyarmor --version >/dev/null 2>&1; then
    PYARMOR_MODULE="pyarmor"
else
    echo "[ERROR] PyArmor is not available for $PYTHON_BIN."
    echo "  Fix: $PYTHON_BIN -m pip install --upgrade pyarmor"
    exit 1
fi

echo "  Staging source files..."
# Copy everything to staging area EXCEPT build artifacts and the staging folder itself
rsync -a --exclude='dist_obf' --exclude='dist' --exclude='build' --exclude='__pycache__' ./ dist_obf/

# Obfuscate only the sensitive modules (under 32KB trial limit)
# These will overwrite the plain-text versions in the dist_obf folder
echo "  Obfuscating sensitive modules..."
"$PYTHON_BIN" -m "$PYARMOR_MODULE" gen --output dist_obf --recursive \
    main.py url.py auth/ monitoring/ utils/



if [ $? -ne 0 ]; then
    echo "[ERROR] PyArmor obfuscation failed"
    exit 1
fi

echo "  [OK] Obfuscation complete"

# Build PyInstaller from obfuscated output
cd "$BACKEND_DIR/dist_obf"
cp "$BACKEND_DIR/enterprise_monitor_backend_mac.spec" .

# Fix the spec file path references (now running from dist_obf)
"$PYTHON_BIN" -m PyInstaller enterprise_monitor_backend_mac.spec --noconfirm

# Move dist back to expected location
rm -rf "$BACKEND_DIR/dist"
mv dist "$BACKEND_DIR/dist"

cd "$BACKEND_DIR"
echo "  [OK] Protected binary: $DIST_DIR"

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