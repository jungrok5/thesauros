"""Ingest historical adjusted-close OHLCV via yfinance → DuckDB prices.

Pattern (same as SEC): parallel fetch → DataFrame collect → single bulk insert.
DuckDB is single-writer, so per-ticker INSERT serializes anyway.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf
from tqdm import tqdm

from app.data.pit_db import connect, cursor


def _last_date_for(ticker: str) -> Optional[date]:
    with cursor() as con:
        row = con.execute(
            "SELECT MAX(date) FROM prices WHERE ticker=?", [ticker]
        ).fetchone()
    return row[0] if row and row[0] else None


def _all_last_dates() -> Dict[str, date]:
    """One-shot query of last date per ticker. Avoids per-worker DB hits."""
    with cursor() as con:
        df = con.execute(
            "SELECT ticker, MAX(date) AS d FROM prices GROUP BY ticker"
        ).df()
    return {r["ticker"]: r["d"] for _, r in df.iterrows() if pd.notna(r["d"])}


def _fetch_one(ticker: str, start: str, end: str) -> pd.DataFrame:
    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            df = t.history(start=start, end=end, auto_adjust=False, actions=False)
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df = df.rename(columns={"Adj Close": "AdjClose"})
                if "AdjClose" not in df.columns:
                    df["AdjClose"] = df["Close"]
                df = df.reset_index().rename(columns={"Date": "date"})
                df["ticker"] = ticker
                return df
        except Exception:
            pass
        time.sleep(0.8 * (attempt + 1))
    return pd.DataFrame()


def _fetch_for_ingest(ticker: str, years: int,
                      last_date: Optional[date] = None) -> pd.DataFrame:
    if last_date is not None:
        start = (last_date + timedelta(days=1)).isoformat()
    else:
        start = (date.today() - timedelta(days=years * 365 + 30)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    if start >= end:
        return pd.DataFrame()
    return _fetch_one(ticker, start, end)


def ingest_universe(tickers: Iterable[str], years: int = 10,
                    workers: int = 8, verbose: bool = True) -> Dict[str, int]:
    """Bulk-fetch + bulk-insert prices."""
    tickers = list(tickers)
    last_dates = _all_last_dates()  # fetch all up-front, no per-worker DB hits
    counts: Dict[str, int] = {}
    frames: List[pd.DataFrame] = []
    pbar = tqdm(total=len(tickers), desc="Prices fetch", disable=not verbose)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch_for_ingest, t, years, last_dates.get(t)): t
                   for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                df = fut.result()
            except Exception as e:
                if verbose:
                    tqdm.write(f"  [{t}] error: {e}")
                df = pd.DataFrame()
            counts[t] = len(df)
            if not df.empty:
                frames.append(df)
            pbar.update(1)
    pbar.close()

    if not frames:
        return counts
    big = pd.concat(frames, ignore_index=True)
    big["date"] = pd.to_datetime(big["date"]).dt.date
    big = big.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "AdjClose": "adj_close", "Volume": "volume",
    })
    keep = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    big = big[[c for c in keep if c in big.columns]]
    big = big.dropna(subset=["date", "ticker"])

    if verbose:
        print(f"[prices] fetched {len(big):,} rows; bulk inserting…")
    con = connect()
    try:
        con.register("df_in", big)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE staging AS
            SELECT ticker, date, open, high, low, close, adj_close, volume FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY ticker, date ORDER BY adj_close DESC
                ) AS rn FROM df_in
            ) WHERE rn = 1
        """)
        con.execute("""
            INSERT OR REPLACE INTO prices
            (ticker, date, open, high, low, close, adj_close, volume)
            SELECT ticker, date, open, high, low, close, adj_close, volume
            FROM staging
        """)
        if verbose:
            n = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            print(f"[prices] table now has {n:,} rows")
    finally:
        con.close()
    return counts
