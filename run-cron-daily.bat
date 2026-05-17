@echo off
REM ===================================================================
REM  Thesauros - daily cron (run locally on PC if GitHub Actions billing
REM  is disabled or repo is private without quota)
REM
REM  Same steps as .github/workflows/daily-scan.yml; recommended to run
REM  ONCE per evening (after 16:00 KST market close).
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
echo   Thesauros daily cron - %date% %time%
echo =====================================================
echo.

echo [1/5] scan_daily (KR + S^&P 500, 2y)...
".venv\Scripts\python.exe" -m app.db.scan_daily --markets KOSPI KOSDAQ NASDAQ NYSE --sp500-only --years 2
if errorlevel 1 echo [WARN] scan_daily failed
echo.

echo [2/5] publish_macro (FRED + yfinance)...
".venv\Scripts\python.exe" -m app.db.publish_macro
if errorlevel 1 echo [WARN] publish_macro failed
echo.

echo [3/5] ingest_themes (Naver)...
".venv\Scripts\python.exe" -m app.db.ingest_themes --themes-only
if errorlevel 1 echo [WARN] ingest_themes failed
echo.

echo [4/5] ingest_investor_flow (KIS)...
".venv\Scripts\python.exe" -m app.db.ingest_investor_flow
if errorlevel 1 echo [WARN] ingest_investor_flow failed
echo.

echo [5/5] telegram_worker (send alerts)...
".venv\Scripts\python.exe" -m app.db.telegram_worker
if errorlevel 1 echo [WARN] telegram_worker failed
echo.

echo =====================================================
echo   Done - %date% %time%
echo =====================================================
endlocal
