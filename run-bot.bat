@echo off
REM ===================================================================
REM  Thesauros - Telegram bot worker (long-poll)
REM    - listens for /link <token> in @candle_trend_bot
REM    - calls /api/telegram/consume on the running web server
REM    - requires: TELEGRAM_BOT_TOKEN, TELEGRAM_LINK_SECRET, WEB_BASE_URL
REM ===================================================================
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)

echo =====================================================
echo   Thesauros telegram bot worker
echo   Mode: long-poll (no webhook needed)
echo   Stop: Ctrl+C
echo =====================================================
echo.

".venv\Scripts\python.exe" -m app.db.telegram_bot --verbose

endlocal
