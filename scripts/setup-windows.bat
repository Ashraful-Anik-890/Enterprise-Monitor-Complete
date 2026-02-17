@echo off
echo ========================================
echo Enterprise Monitor - Windows Setup
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.11+ from https://www.python.org/
    pause
    exit /b 1
)

REM Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found!
    echo Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

echo [1/6] Setting up Python backend...
cd backend-windows

REM Create virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate

REM Install dependencies
echo Installing Python dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pywin32

echo.
echo [2/6] Python backend setup complete!
echo.

REM Setup Electron app
cd ..\electron-app

echo [3/6] Installing Electron dependencies...
call npm install

echo.
echo [4/6] Building TypeScript...
call npm run build

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo To run the application:
echo.
echo 1. Start backend:
echo    cd backend-windows
echo    venv\Scripts\activate
echo    python main.py
echo.
echo 2. Start Electron (new terminal):
echo    cd electron-app
echo    npm start
echo.
echo Default login: admin / admin123
echo.
pause
