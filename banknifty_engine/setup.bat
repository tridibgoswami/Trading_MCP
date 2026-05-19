@echo off
:: ─────────────────────────────────────────────
:: BankNifty MCP Engine — Windows Setup
:: Run this ONCE before starting the engine.
:: Double-click this file or run in CMD.
:: ─────────────────────────────────────────────

title BankNifty Engine Setup
color 0A
echo.
echo ============================================
echo   BANKNIFTY MCP ENGINE — WINDOWS SETUP
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [OK] Python found

:: Create virtual environment
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

:: Activate venv and install packages
echo.
echo Installing packages (this takes 1-2 minutes)...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Package installation failed. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] All packages installed

:: Create .env from template
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [OK] .env file created from template
    echo.
    echo ============================================
    echo   IMPORTANT: Open .env and fill in your
    echo   AngelOne + Anthropic + Telegram details
    echo ============================================
) else (
    echo [OK] .env already exists
)

:: Create required directories
if not exist "data_store" mkdir data_store
if not exist "logs" mkdir logs
if not exist "reports" mkdir reports
echo [OK] Directories ready

echo.
echo ============================================
echo   SETUP COMPLETE
echo ============================================
echo.
echo Next steps:
echo   1. Open .env and fill in your credentials
echo   2. Double-click start_engine.bat to start
echo   3. Run ngrok_webhook.bat to expose webhook
echo.
pause
