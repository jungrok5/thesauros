@echo off
REM ===================================================================
REM  Thesauros - Next.js frontend only (port 3000)
REM ===================================================================
setlocal
cd /d "%~dp0"

set FRONTEND_PORT=3000

if not exist "web-next\node_modules" (
    echo [ERROR] web-next\node_modules not found. Run:
    echo         cd web-next ^&^& npm install
    pause
    exit /b 1
)

netstat -ano | findstr :%FRONTEND_PORT% | findstr LISTENING >nul
if not errorlevel 1 (
    echo [WARN] Port %FRONTEND_PORT% already in use. Kill existing first or change port.
    pause
    exit /b 1
)

echo =====================================================
echo   Thesauros frontend
echo   http://localhost:%FRONTEND_PORT%
echo   Stop: Ctrl+C
echo =====================================================
echo.

cd web-next
call npm run dev -- --port %FRONTEND_PORT%

endlocal
