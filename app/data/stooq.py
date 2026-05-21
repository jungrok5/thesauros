"""Stooq EOD CSV fallback for US OHLCV bars.

Stooq publishes free historical EOD as a plain CSV download. Unlike
Naver and yfinance it does NOT appear to block GH Actions cloud IPs,
which makes it the natural second source when Naver's rate-limit
cascade trips the circuit breaker for US tickers.

Endpoint:
  GET https://stooq.com/q/d/l/?s=<symbol>.us&i=<w|m>

  - i=w → weekly bars (~5 years available)
  - i=m → monthly bars (~9 years available)
  - response body: CSV with header `Date,Open,High,Low,Close,Volume`
    or the literal string "No data" for symbols Stooq doesn't have.

Why not use Stooq as the *primary* source for US bars? Two reasons:

  1. Stooq's symbol coverage is much narrower than Naver — small caps,
     SPACs, recent IPOs are often missing. Naver covers everything that
     trades on US exchanges.
  2. Stooq's volume figures differ from the consolidated tape (they
     appear to sample one venue), so our 거래량 폭증 signal would shift
     thresholds. Naver's volume matches what Korean retail tools display.

So Stooq is "good enough" for filling bars when Naver is blocked, but
we keep Naver as the canonical source so the engine's signals stay
calibrated to the same numbers users see elsewhere.

Schema: returns the SAME columns/dtypes as `naver_bars.fetch_weekly` so
callers can drop in interchangeably:
  [date (Timestamp), open, high, low, close, adj_close, volume]

Stooq doesn't expose a separate adj_close field — for our cash-equity
US universe the difference is small and book MAs are on `close` anyway,
so we fill adj_close with close (mirrors what naver_bars does).
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

_BASE = "https://stooq.com/q/d/l/"
_HEADERS = {
    # Stooq throttles requests that don't look browser-ish; a plain
    # python-requests UA returns 403 even for valid symbols.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
_TIMEOUT = 15

# Stooq US symbols are lower-case with ".us" suffix. Some special cases:
#   class-share dot tickers (e.g. BRK.B) become "brk-b.us".
#   plain tickers (AAPL) → "aapl.us"
# We do NOT try multiple suffixes the way naver_bars does — Stooq's
# US namespace is unambiguous.


def _stooq_symbol(ticker: str) -> str:
    t = ticker.strip().lower()
    # Replace dot with dash for class-share notation. Avoids double
    # suffix if caller already passed the stooq form.
    if t.endswith(".us"):
        return t
    t = t.replace(".", "-")
    return f"{t}.us"


def _fetch_csv(ticker: str, interval: str) -> Optional[pd.DataFrame]:
    """interval ∈ {"w", "m"} — Stooq's weekly/monthly buckets."""
    symbol = _stooq_symbol(ticker)
    params = {"s": symbol, "i": interval}
    try:
        r = requests.get(
            _BASE, params=params, headers=_HEADERS, timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        log.debug("stooq fetch %s/%s failed: %s", symbol, interval, e)
        return None
    if r.status_code != 200:
        log.debug("stooq %s/%s HTTP %s", symbol, interval, r.status_code)
        return None
    text = r.text or ""
    # Stooq returns "No data" (with newline) or an HTML "Exceeded the
    # daily hits limit" page for missing / rate-limited symbols.
    if not text or text.startswith("<") or "No data" in text[:32]:
        return None
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        log.debug("stooq parse %s/%s: %s", symbol, interval, e)
        return None
    if df is None or df.empty:
        return None
    # Stooq's column casing is Capitalized — normalize to our schema.
    rename = {
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    df = df.rename(columns=rename)
    needed = {"date", "open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df["adj_close"] = df["close"]
    df = df.dropna(subset=["close"])
    df = df[["date", "open", "high", "low", "close", "adj_close", "volume"]]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_weekly(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Weekly OHLCV via Stooq. `years` is informational — Stooq always
    returns the full available history (typically 5+ years for weekly).
    Caller can slice if needed."""
    df = _fetch_csv(ticker, "w")
    if df is None:
        return None
    df.attrs["grain"] = "W"
    return df


def fetch_monthly(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Monthly OHLCV via Stooq."""
    df = _fetch_csv(ticker, "m")
    if df is None:
        return None
    df.attrs["grain"] = "M"
    return df
