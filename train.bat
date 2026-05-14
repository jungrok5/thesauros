@echo off
REM Train the LightGBM model from current DuckDB data
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (echo [ERR] .venv not found. & pause & exit /b 1)

set PYTHONIOENCODING=utf-8
chcp 65001 >nul

echo ============================================================
echo  Train LightGBM (PurgedKFold + Embargo)
echo ============================================================

".venv\Scripts\python.exe" -m app.train --use-rank --start 2014-01-01

echo.
pause
endlocal
