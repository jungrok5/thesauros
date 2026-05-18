"""Naver Finance OHLCV fallback for US tickers.

yfinance is rate-limited / blocked when called from cloud (AWS/GCP/Azure)
IPs — the GitHub Actions Azure runner gets `Expecting value: line 1
column 1 (char 0)` for every US ticker. Naver's public chart API has
no IP block and works fine from those runners.

Endpoint: GET https://api.stock.naver.com/chart/foreign/item/{symbol}
  params: startDateTime, endDateTime (yyyyMMddHHmmss), periodType
  periodType values that work: dayCandle, weekCandle, monthCandle, yearCandle

Hard caps observed (2026-05-18):
  dayCandle   → 110 rows (~5.5 months daily) — too short for book MAs
  weekCandle  → 110 rows (~2 years weekly)
  monthCandle → 110 rows (~9 years monthly)

So this module exposes weekly + monthly fetches only. Book's primary
signals are monthly 240MA + monthly/weekly 10MA, so weekly is the
natural unit for swing analysis.

Symbol format: NASDAQ → "AAPL.O", NYSE → "DELL.K", AMEX → "XYZ.A"
The "." suffix is required. Plain "AAPL" returns 404.

The same yfinance ticker we use everywhere else (e.g. "AAPL", "MSFT")
maps to Naver's "AAPL.O" / "MSFT.O" for NASDAQ names. NYSE names need
"X.K". `resolve_naver_symbol()` tries both and returns whichever has data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

_BASE = "https://api.stock.naver.com/chart/foreign/item"
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://m.stock.naver.com/",
}
_TIMEOUT = 10


def _fetch(symbol: str, period_type: str, years: int) -> Optional[pd.DataFrame]:
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=int(years * 365) + 30)
    params = {
        "startDateTime": start.strftime("%Y%m%d%H%M%S"),
        "endDateTime": end.strftime("%Y%m%d%H%M%S"),
        "periodType": period_type,
    }
    try:
        r = requests.get(
            f"{_BASE}/{symbol}", params=params, headers=_HEADERS, timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        log.warning("naver fetch %s/%s failed: %s", symbol, period_type, e)
        return None
    if r.status_code != 200:
        log.warning("naver %s/%s HTTP %s", symbol, period_type, r.status_code)
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    infos = payload.get("priceInfos") or []
    if not infos:
        return None
    df = pd.DataFrame(infos)
    rename = {
        "localDate": "date",
        "openPrice": "open",
        "highPrice": "high",
        "lowPrice": "low",
        "closePrice": "close",
        "accumulatedTradingVolume": "volume",
    }
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # No adj-close on Naver — book's MAs use close anyway. Fill with close
    # so downstream code that reads adj_close doesn't NaN-out.
    df["adj_close"] = df["close"]
    df = df[["date", "open", "high", "low", "close", "adj_close", "volume"]]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _try_suffixes(plain_ticker: str, period_type: str, years: int) -> Optional[pd.DataFrame]:
    # Most US tickers are NASDAQ ("X.O"); fall back to NYSE ("X.K") and AMEX ("X.A").
    for suffix in (".O", ".K", ".A"):
        df = _fetch(plain_ticker + suffix, period_type, years)
        if df is not None and not df.empty:
            return df
    return None


def fetch_weekly(ticker: str, years: int = 2) -> Optional[pd.DataFrame]:
    """Weekly OHLCV bars for a US ticker via Naver. Returns DataFrame
    with columns [date, open, high, low, close, adj_close, volume] or
    None. `date` is the week-ending date (Naver returns Monday-anchored
    weekly closes in practice; the exact anchor is informational).

    Naver caps responses at ~110 rows regardless of date range, which
    is roughly 2 years of weekly bars — enough for book's MAs and
    multi-timeframe trend assessment.
    """
    df = _try_suffixes(ticker.upper(), "weekCandle", years)
    if df is None:
        return None
    df.attrs["grain"] = "W"
    return df


def fetch_monthly(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Monthly OHLCV bars for a US ticker via Naver."""
    df = _try_suffixes(ticker.upper(), "monthCandle", years)
    if df is None:
        return None
    df.attrs["grain"] = "M"
    return df
