@echo off
:: ─────────────────────────────────────────────
:: BankNifty MCP Engine — Windows Startup
:: Double-click this every morning before market.
:: ─────────────────────────────────────────────

title BankNifty Engine
color 0A
cd /d "%~dp0"

:: Activate virtual environment
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

:: Check .env exists
if not exist ".env" (
    echo [ERROR] .env file not found.
    echo Please run setup.bat and fill in your credentials.
    pause
    exit /b 1
)

echo.
echo Starting BankNifty MCP Engine...
echo Press Ctrl+C to stop.
echo.

python start_engine.py
pause
