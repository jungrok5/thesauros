"""Tiingo US equity bars fetcher (Phase 6 ad-hoc analysis).

Tiingo is the chosen US data source for book ad-hoc analysis:
  - Free tier: 500 requests / day (no cloud IP block, unlike yfinance)
  - 5+ years of weekly/monthly history (covers 240MA pattern detection)
  - Stable API, good docs

Sign up at https://www.tiingo.com → free → get token → set env:
  TIINGO_API_KEY=<your-token>

Endpoint:
  GET https://api.tiingo.com/tiingo/daily/{ticker}/prices
    ?startDate=2021-01-01&endDate=2026-05-22&resampleFreq=weekly
    &token={TIINGO_API_KEY}

Returns JSON: [{"date":..., "close":..., "open":..., "high":..., "low":...,
                 "volume":..., "adjClose":..., "adjOpen":..., ...}]

Resampled bars (weekly/monthly) come pre-aggregated server-side, so no
local resampling needed.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Dict, List, Optional

import requests


TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"
DEFAULT_HISTORY_DAYS = 5 * 365 + 7      # ~5 years
REQUEST_TIMEOUT = 15


class TiingoError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("TIINGO_API_KEY", "").strip()
    if not key:
        raise TiingoError(
            "TIINGO_API_KEY env not set. Sign up at https://www.tiingo.com "
            "(free 500 req/day) and set TIINGO_API_KEY=<your-token>."
        )
    return key


def fetch_bars(
    ticker: str,
    granularity: str = "W",
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[Dict]:
    """Fetch resampled bars from Tiingo.

    granularity:
        'W' → weekly (Friday close)
        'M' → monthly (last business day close)
    Returns: list of dicts with keys: date (ISO), open, high, low, close,
             adj_close, volume.
    Raises TiingoError on non-2xx or missing token.
    """
    if granularity not in ("W", "M"):
        raise TiingoError(f"granularity must be 'W' or 'M', got {granularity!r}")

    end = end or date.today()
    start = start or (end - timedelta(days=DEFAULT_HISTORY_DAYS))
    resample = "weekly" if granularity == "W" else "monthly"

    url = f"{TIINGO_BASE}/{ticker.upper()}/prices"
    params = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "resampleFreq": resample,
        "token": _api_key(),
        "format": "json",
    }
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise TiingoError(f"network error: {e}") from e

    if r.status_code == 404:
        raise TiingoError(f"ticker not found: {ticker}")
    if r.status_code == 429:
        raise TiingoError("Tiingo rate limit (500/day free) exceeded")
    if not r.ok:
        raise TiingoError(f"Tiingo HTTP {r.status_code}: {r.text[:200]}")

    rows = r.json()
    if not isinstance(rows, list):
        raise TiingoError(f"unexpected response shape: {type(rows).__name__}")

    out: List[Dict] = []
    for row in rows:
        d = row.get("date", "")[:10]     # 2023-01-13T00:00:00.000Z → 2023-01-13
        if not d:
            continue
        out.append({
            "date": d,
            "open": float(row.get("adjOpen") or row.get("open") or 0),
            "high": float(row.get("adjHigh") or row.get("high") or 0),
            "low": float(row.get("adjLow") or row.get("low") or 0),
            "close": float(row.get("adjClose") or row.get("close") or 0),
            "adj_close": float(row.get("adjClose") or row.get("close") or 0),
            "volume": int(row.get("adjVolume") or row.get("volume") or 0),
        })
    return out


def fetch_ticker_meta(ticker: str) -> Dict:
    """Fetch ticker metadata (name, exchange) from Tiingo.

    Endpoint: /tiingo/daily/{ticker}
    Returns: {name, exchangeCode, startDate, endDate, description}
    """
    url = f"{TIINGO_BASE}/{ticker.upper()}"
    params = {"token": _api_key()}
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise TiingoError(f"network error: {e}") from e
    if r.status_code == 404:
        raise TiingoError(f"ticker not found: {ticker}")
    if not r.ok:
        raise TiingoError(f"Tiingo HTTP {r.status_code}")
    return r.json()


if __name__ == "__main__":
    # Smoke test: python -m app.data.us_bars_tiingo AAPL
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    try:
        bars = fetch_bars(ticker, "W")
        print(f"weekly: {len(bars)} bars, first {bars[0]['date']} → last {bars[-1]['date']}")
        meta = fetch_ticker_meta(ticker)
        print(f"meta:   {meta.get('name')} ({meta.get('exchangeCode')})")
    except TiingoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
