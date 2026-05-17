@echo off
REM ===================================================================
REM  Thesauros - dev frontend launcher
REM
REM  Site reads Supabase directly (no FastAPI). Daily cron lives in
REM  GitHub Actions in prod. Telegram bot uses webhook in prod (Vercel
REM  route /api/telegram/webhook), so no long-poll worker needed.
REM ===================================================================
setlocal
cd /d "%~dp0"

set FRONTEND_PORT=3000

echo.
echo =====================================================
echo   Thesauros - dev stack
echo =====================================================
echo   Frontend : http://localhost:%FRONTEND_PORT%
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
echo Starting Next.js frontend on :%FRONTEND_PORT% ...
start "thesauros-frontend" cmd /k "cd web-next && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 6 /nobreak >nul

REM --- open browser ---
echo.
echo Opening browser...
start http://localhost:%FRONTEND_PORT%

echo.
echo =====================================================
echo   Frontend running. Press any key in THIS window to STOP.
echo =====================================================
echo.
pause >nul

REM --- stop everything ---
echo.
echo Stopping...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a /T >nul 2>&1
)

taskkill /F /FI "WINDOWTITLE eq thesauros-frontend*" /T >nul 2>&1

echo Stopped. Bye.
endlocal
