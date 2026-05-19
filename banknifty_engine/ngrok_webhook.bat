@echo off
:: ─────────────────────────────────────────────
:: Expose the webhook to TradingView via ngrok.
:: Run this alongside start_engine.bat.
::
:: One-time setup:
::   1. Download ngrok from https://ngrok.com/download
::   2. Unzip ngrok.exe to this folder (or add to PATH)
::   3. Run: ngrok config add-authtoken YOUR_TOKEN
::      (free token from https://dashboard.ngrok.com)
:: ─────────────────────────────────────────────

title ngrok — BankNifty Webhook
cd /d "%~dp0"

:: Load webhook port from .env
set WEBHOOK_PORT=5050
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if "%%a"=="WEBHOOK_PORT" set WEBHOOK_PORT=%%b
)

echo.
echo Starting ngrok tunnel on port %WEBHOOK_PORT%...
echo.
echo Once running, copy the https://xxxx.ngrok-free.app URL
echo and use it as your TradingView webhook URL:
echo   https://xxxx.ngrok-free.app/signal
echo.

ngrok http %WEBHOOK_PORT%
pause
