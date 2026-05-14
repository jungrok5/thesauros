@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

REM ===================================================================
REM  Thesauros — dev mode launcher
REM  FastAPI backend + Next.js frontend in separate windows.
REM  Press any key in this window to stop both and exit.
REM ===================================================================

set BACKEND_PORT=8001
set FRONTEND_PORT=3000

echo.
echo =====================================================
echo   Thesauros — dev mode
echo =====================================================
echo   Backend  : http://127.0.0.1:%BACKEND_PORT%
echo   Frontend : http://localhost:%FRONTEND_PORT%
echo =====================================================
echo.

REM --- sanity check: .venv exists ---
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

REM --- check ports ---
netstat -ano | findstr :%BACKEND_PORT% | findstr LISTENING > nul && (
    echo [WARN] Port %BACKEND_PORT% already in use. Backend may fail to start.
)
netstat -ano | findstr :%FRONTEND_PORT% | findstr LISTENING > nul && (
    echo [WARN] Port %FRONTEND_PORT% already in use. Frontend may fail to start.
)

REM --- start backend ---
echo [1/2] Starting FastAPI backend on :%BACKEND_PORT% ...
start "thesauros-backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.api.server:app --reload --host 127.0.0.1 --port %BACKEND_PORT%"
timeout /t 3 /nobreak > nul

REM --- start frontend ---
echo [2/2] Starting Next.js frontend on :%FRONTEND_PORT% ...
start "thesauros-frontend" cmd /k "cd web-next && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 6 /nobreak > nul

REM --- open browser ---
echo.
echo Opening browser...
start http://localhost:%FRONTEND_PORT%

echo.
echo =====================================================
echo   Both servers running.
echo   Press any key in THIS window to STOP both.
echo =====================================================
echo.
pause > nul

REM --- stop both servers (kill processes listening on the ports) ---
echo.
echo Stopping...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a /T > nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a /T > nul 2>&1
)

echo Stopped. Bye.
endlocal
