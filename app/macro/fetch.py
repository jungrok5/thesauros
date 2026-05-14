"""Fetch macro indicators from FRED + yfinance and cache in DuckDB.

Schema (new table `macro`):
  series_id  VARCHAR
  date       DATE
  value      DOUBLE
  PRIMARY KEY (series_id, date)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from app.config import FRED_API_KEY
from app.data.pit_db import connect, cursor
from app.macro.indicators import INDICATORS, get_indicator


MACRO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS macro (
    series_id VARCHAR,
    date      DATE,
    value     DOUBLE,
    PRIMARY KEY (series_id, date)
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro(date);
"""


def ensure_macro_schema() -> None:
    with cursor() as con:
        con.execute(MACRO_SCHEMA_SQL)


def _fetch_fred(series_id: str, start: Optional[str] = None) -> pd.DataFrame:
    """Fetch a single FRED series. Returns DataFrame with date, value columns."""
    if not FRED_API_KEY:
        raise RuntimeError(
            "FRED_API_KEY env var not set. Register at https://fred.stlouisfed.org/ "
            "and export FRED_API_KEY=..."
        )
    from fredapi import Fred
    fred = Fred(api_key=FRED_API_KEY)
    s = fred.get_series(series_id, observation_start=start)
    df = s.dropna().reset_index()
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()


def _fetch_yf(series_id: str, start: Optional[str] = None) -> pd.DataFrame:
    """Fetch a yfinance ticker — use Close as the value."""
    import yfinance as yf
    if start is None:
        start = (date.today() - timedelta(days=365 * 6)).isoformat()
    t = yf.Ticker(series_id)
    df = t.history(start=start, auto_adjust=False, actions=False)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "value"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    out = df[["Close"]].reset_index().rename(columns={"Date": "date", "Close": "value"})
    out["date"] = pd.to_datetime(out["date"]).dt.date
    return out.dropna()


def _last_date(series_id: str) -> Optional[date]:
    with cursor() as con:
        row = con.execute(
            "SELECT MAX(date) FROM macro WHERE series_id = ?", [series_id]
        ).fetchone()
    return row[0] if row and row[0] else None


def ingest_one(series_id: str, source: str, years: int = 8) -> int:
    """Fetch + upsert a single macro series. Returns rows inserted."""
    ensure_macro_schema()
    last = _last_date(series_id)
    if last is not None:
        start = (last + timedelta(days=1)).isoformat()
    else:
        start = (date.today() - timedelta(days=years * 365 + 30)).isoformat()

    if source == "FRED":
        df = _fetch_fred(series_id, start=start)
    elif source == "yfinance":
        df = _fetch_yf(series_id, start=start)
    else:
        raise ValueError(f"unknown source: {source}")

    if df.empty:
        return 0

    df = df.assign(series_id=series_id)[["series_id", "date", "value"]]
    con = connect()
    try:
        con.register("df_in", df)
        con.execute("""
            INSERT OR REPLACE INTO macro(series_id, date, value)
            SELECT series_id, date, value FROM df_in
        """)
    finally:
        con.close()
    return len(df)


def ingest_all(years: int = 8, indicators: Optional[List[Dict]] = None,
               skip_fred_if_no_key: bool = True, verbose: bool = True) -> Dict[str, int]:
    """Fetch all configured indicators. Skips FRED if no API key when configured."""
    counts: Dict[str, int] = {}
    inds = indicators if indicators is not None else INDICATORS
    have_fred = bool(FRED_API_KEY)
    for ind in inds:
        key, source, sid = ind["key"], ind["source"], ind["series_id"]
        if source == "FRED" and not have_fred:
            if skip_fred_if_no_key:
                if verbose:
                    print(f"  [{key}] SKIP (no FRED_API_KEY)")
                counts[key] = 0
                continue
        try:
            n = ingest_one(sid, source, years=years)
            counts[key] = n
            if verbose:
                print(f"  [{key}] +{n} rows  ({sid})")
        except Exception as e:
            counts[key] = -1
            if verbose:
                print(f"  [{key}] ERROR: {e}")
    return counts


def latest_value(series_id: str) -> Optional[Dict]:
    """Most recent (date, value) for a series."""
    with cursor() as con:
        row = con.execute(
            "SELECT date, value FROM macro WHERE series_id = ? ORDER BY date DESC LIMIT 1",
            [series_id],
        ).fetchone()
    if not row:
        return None
    return {"date": row[0], "value": row[1]}


def history(series_id: str, years: int = 5) -> pd.DataFrame:
    """Pull cached history for a series as DataFrame."""
    start = date.today() - timedelta(days=years * 365)
    with cursor() as con:
        return con.execute(
            "SELECT date, value FROM macro WHERE series_id=? AND date >= ? ORDER BY date",
            [series_id, start],
        ).df()
