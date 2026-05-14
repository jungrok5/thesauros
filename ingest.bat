@echo off
REM Ingest universe + SEC fundamentals + prices into DuckDB
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERR] .venv not found. Run install.bat first.
    pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
chcp 65001 >nul

echo ============================================================
echo  Data Ingestion - S^&P 500 PIT Database
echo ============================================================
echo  This will:
echo   1) Build S^&P 500 universe (Wikipedia + SEC ticker map)
echo   2) Fetch SEC EDGAR Company Facts (~1.5M rows, ~2 min)
echo   3) Fetch 10y daily prices for ~500 tickers (~5 min)
echo  Output: data\pit.duckdb (~500 MB)
echo ============================================================
echo.

".venv\Scripts\python.exe" -c "from app.data.universe import build_universe; build_universe()"
if errorlevel 1 (echo [ERR] universe build failed & pause & exit /b 1)

".venv\Scripts\python.exe" -c "from app.data.pit_db import cursor; from app.data.ingest_sec import ingest_universe; rows=cursor().__enter__().execute('SELECT ticker,cik FROM universe WHERE cik IS NOT NULL').fetchall(); ingest_universe(rows, workers=8)"
if errorlevel 1 (echo [ERR] SEC ingest failed & pause & exit /b 1)

".venv\Scripts\python.exe" -c "from app.data.universe import get_active_tickers; from app.data.ingest_prices import ingest_universe; ingest_universe(get_active_tickers(), years=10, workers=8)"
if errorlevel 1 (echo [ERR] prices ingest failed & pause & exit /b 1)

".venv\Scripts\python.exe" -c "from app.data.pit_db import stats; import json; print(json.dumps(stats(), indent=2, default=str))"

echo.
echo ============================================================
echo  Ingestion complete. Run train.bat next.
echo ============================================================
pause
endlocal
