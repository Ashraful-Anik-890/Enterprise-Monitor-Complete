#!/bin/bash

echo "========================================"
echo "Enterprise Monitor - macOS Setup"
echo "========================================"
echo ""

# Check Swift
if ! command -v swift &> /dev/null; then
    echo "[ERROR] Swift not found!"
    echo "Please install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found!"
    echo "Please install Node.js 18+ from https://nodejs.org/"
    echo "Or use Homebrew: brew install node"
    exit 1
fi

echo "[1/6] Setting up Swift backend..."
cd backend-macos

echo "Resolving Swift dependencies..."
swift package resolve

echo "Building Swift project..."
swift build

echo ""
echo "[2/6] Swift backend setup complete!"
echo ""

# Setup Electron app
cd ../electron-app

echo "[3/6] Installing Electron dependencies..."
npm install

echo ""
echo "[4/6] Building TypeScript..."
npm run build

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "To run the application:"
echo ""
echo "1. Start backend:"
echo "   cd backend-macos"
echo "   swift run"
echo ""
echo "2. Start Electron (new terminal):"
echo "   cd electron-app"
echo "   npm start"
echo ""
echo "Default login: admin / admin123"
echo ""
echo "IMPORTANT: Grant Screen Recording permission when prompted!"
echo ""
