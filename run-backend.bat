@echo off
REM ===================================================================
REM  Thesauros - FastAPI backend only (port 8001)
REM ===================================================================
setlocal
cd /d "%~dp0"

set BACKEND_PORT=8001
set PYTHONIOENCODING=utf-8
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)

netstat -ano | findstr :%BACKEND_PORT% | findstr LISTENING >nul
if not errorlevel 1 (
    echo [WARN] Port %BACKEND_PORT% already in use. Kill existing first or change port.
    pause
    exit /b 1
)

echo =====================================================
echo   Thesauros backend
echo   http://127.0.0.1:%BACKEND_PORT%
echo   Stop: Ctrl+C
echo =====================================================
echo.

".venv\Scripts\python.exe" -m uvicorn app.api.server:app --reload --host 127.0.0.1 --port %BACKEND_PORT%

endlocal
