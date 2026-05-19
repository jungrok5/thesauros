"""Fetch macro indicators from FRED + Yahoo v8 chart API and cache in Supabase.

Cache table is `macro_series` (migration 007):
    series_id VARCHAR(40), date DATE, value NUMERIC, PRIMARY KEY (series_id, date)

The macro state cron (`app.db.publish_macro`) calls `latest_value` / `history`
which read from Supabase. `ingest_all` is also called from the same cron to
refresh the cache before publishing.

NB on Yahoo: the `yfinance` Python lib detects + blocks cloud-IP traffic
(Azure ranges in particular), so the same call from a GH Actions runner
returns 401/empty. We call Yahoo's underlying v8 chart endpoint directly
(`query1.finance.yahoo.com/v8/finance/chart/{symbol}`) — same data, no
lib-side blocklist, and we control the User-Agent.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
import requests

from app.config import FRED_API_KEY
from app.db import get_conn
from app.macro.indicators import INDICATORS

_YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


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
    """Fetch daily closes via Yahoo's v8 chart endpoint (bypasses yfinance
    lib's cloud-IP blocklist). Returns DataFrame with (date, value) columns
    where `value` is the unadjusted close.
    """
    if start is None:
        start = (date.today() - timedelta(days=365 * 6)).isoformat()
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    period1 = int(start_dt.timestamp())
    period2 = int(datetime.now(tz=timezone.utc).timestamp())

    url = _YF_CHART_URL.format(sym=series_id)
    params = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "includePrePost": "false",
        "events": "div,split",
    }
    try:
        res = requests.get(url, params=params, headers=_YF_HEADERS, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"yahoo chart fetch failed: {e}") from e
    if res.status_code != 200:
        # 401/404 are the typical "no data" responses; return empty frame
        # so the caller can keep going with the rest of the indicators.
        return pd.DataFrame(columns=["date", "value"])
    payload = res.json()
    chart = (payload or {}).get("chart") or {}
    err = chart.get("error")
    if err:
        return pd.DataFrame(columns=["date", "value"])
    results = chart.get("result") or []
    if not results:
        return pd.DataFrame(columns=["date", "value"])
    r = results[0]
    timestamps = r.get("timestamp") or []
    closes = (((r.get("indicators") or {}).get("quote") or [{}])[0]
              .get("close") or [])
    rows: List[Dict] = []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        rows.append({"date": d, "value": float(c)})
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    out = pd.DataFrame(rows)
    return out.dropna()


def _last_date(series_id: str) -> Optional[date]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM macro_series WHERE series_id = %s",
                (series_id,),
            )
            row = cur.fetchone()
    return row[0] if row and row[0] else None


def ingest_one(series_id: str, source: str, years: int = 8) -> int:
    """Fetch + upsert a single macro series. Returns rows inserted."""
    last = _last_date(series_id)
    if last is not None:
        start = (last + timedelta(days=1)).isoformat()
    else:
        start = (date.today() - timedelta(days=years * 365 + 30)).isoformat()

    if source == "FRED":
        df = _fetch_fred(series_id, start=start)
    elif source == "yfinance":
        # Legacy tag — the actual fetcher uses Yahoo's v8 chart endpoint
        # directly. See module docstring for the why.
        df = _fetch_yf(series_id, start=start)
    else:
        raise ValueError(f"unknown source: {source}")

    if df.empty:
        return 0

    rows = [(series_id, r.date, float(r.value)) for r in df.itertuples()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO macro_series (series_id, date, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (series_id, date) DO UPDATE SET value = EXCLUDED.value
                """,
                rows,
            )
    return len(rows)


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
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, value FROM macro_series WHERE series_id = %s "
                "ORDER BY date DESC LIMIT 1",
                (series_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {"date": row[0], "value": float(row[1]) if row[1] is not None else None}


def history(series_id: str, years: int = 5) -> pd.DataFrame:
    """Pull cached history for a series as DataFrame (date, value)."""
    start = date.today() - timedelta(days=years * 365)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, value FROM macro_series "
                "WHERE series_id = %s AND date >= %s ORDER BY date",
                (series_id, start),
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["date", "value"])
