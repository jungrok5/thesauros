"""Backfill US memory/semi weekly bars for Phase 14 (MU lead-lag).

Tickers: MU (Micron), NVDA (NVIDIA), TSM (TSMC), AAPL — top-line drivers
that influence the KR memory chain (Hynix, Samsung, 한미반도체).

Yahoo v8 chart API direct call — yfinance lib detects cloud IPs and
returns empty for Azure ranges, the same pattern we already work
around in app/macro/fetch.py. Reuses that pattern.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "backtest.duckdb"

TICKERS = ["MU", "NVDA", "TSM", "AAPL"]
START_TS = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
END_TS = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp())

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
}


def fetch_weekly(symbol: str, max_retries: int = 5) -> pd.DataFrame:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={START_TS}&period2={END_TS}&interval=1wk"
    )
    backoff = 5
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 429:
                print(f"  {symbol}: 429 - sleeping {backoff}s "
                      f"(attempt {attempt+1}/{max_retries})", flush=True)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)
                continue
            r.raise_for_status()
            break
        except requests.exceptions.HTTPError:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff)
            backoff = min(60, backoff * 2)
    data = r.json()["chart"]["result"][0]
    ts = data["timestamp"]
    q = data["indicators"]["quote"][0]
    adj = data["indicators"].get("adjclose", [{}])[0].get("adjclose")
    df = pd.DataFrame({
        "bar_date": pd.to_datetime(ts, unit="s", utc=True).date,
        "open": q["open"],
        "high": q["high"],
        "low": q["low"],
        "close": q["close"],
        "adj_close": adj if adj else q["close"],
        "volume": q["volume"],
    })
    df = df.dropna(subset=["close"])
    return df


def main() -> int:
    con = duckdb.connect(str(DB_PATH))
    for tic in TICKERS:
        t0 = time.time()
        df = fetch_weekly(tic)
        df["ticker"] = tic
        df["granularity"] = "W"
        df = df[[
            "ticker", "granularity", "bar_date",
            "open", "high", "low", "close", "adj_close", "volume",
        ]]
        con.register("_tmp", df)
        con.execute("INSERT OR REPLACE INTO bars SELECT * FROM _tmp")
        con.unregister("_tmp")
        n = con.sql(
            f"SELECT COUNT(*), MIN(bar_date), MAX(bar_date) FROM bars "
            f"WHERE ticker='{tic}' AND granularity='W'"
        ).fetchone()
        print(f"  {tic:>5}: {n[0]} rows ({n[1]} to {n[2]}) "
              f"in {time.time()-t0:.1f}s", flush=True)
        time.sleep(15)   # Yahoo rate-limit pacing — spread tickers
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
