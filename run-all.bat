@echo off
REM ===================================================================
REM  Thesauros - dev stack (frontend + telegram bot)
REM
REM  After Phase 6 cleanup there is no FastAPI backend — the site reads
REM  Supabase directly. Daily/weekly cron is GitHub Actions in prod.
REM
REM  Opens 2 separate console windows so each process's logs are
REM  isolated; Ctrl+C in this window will cleanly stop BOTH.
REM ===================================================================
setlocal
cd /d "%~dp0"

set FRONTEND_PORT=3000

echo.
echo =====================================================
echo   Thesauros - dev stack
echo =====================================================
echo   Frontend : http://localhost:%FRONTEND_PORT%
echo   Bot      : long-poll (telegram)
echo =====================================================
echo.

REM --- sanity checks ---
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)
if not exist "web-next\node_modules" (
    echo [ERROR] web-next\node_modules not found. Run:
    echo         cd web-next ^&^& npm install
    pause
    exit /b 1
)

REM --- check port already in use ---
netstat -ano | findstr :%FRONTEND_PORT% | findstr LISTENING >nul
if not errorlevel 1 echo [WARN] Port %FRONTEND_PORT% already in use. Frontend may fail.

REM --- start frontend ---
echo [1/2] Starting Next.js frontend on :%FRONTEND_PORT% ...
start "thesauros-frontend" cmd /k "cd web-next && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 6 /nobreak >nul

REM --- start telegram bot worker ---
echo [2/2] Starting Telegram bot worker (long-poll) ...
start "thesauros-bot" cmd /k ".venv\Scripts\python.exe -m app.db.telegram_bot --verbose"
timeout /t 2 /nobreak >nul

REM --- open browser ---
echo.
echo Opening browser...
start http://localhost:%FRONTEND_PORT%

echo.
echo =====================================================
echo   Both processes running in their own windows.
echo   Press any key in THIS window to STOP both.
echo =====================================================
echo.
pause >nul

REM --- stop everything ---
echo.
echo Stopping...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a /T >nul 2>&1
)

taskkill /F /FI "WINDOWTITLE eq thesauros-bot*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq thesauros-frontend*" /T >nul 2>&1

echo Stopped. Bye.
endlocal
