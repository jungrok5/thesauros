"""Naver Finance OHLCV fallback for US tickers.

yfinance is rate-limited / blocked when called from cloud (AWS/GCP/Azure)
IPs — the GitHub Actions Azure runner gets `Expecting value: line 1
column 1 (char 0)` for every US ticker. Naver's public chart API does
NOT have a hard IP block, but it DOES rate-limit aggressively from the
same cloud IPs: once we exceed ~50 req/min from an Azure runner Naver
silently starts dropping our packets and every subsequent call hits the
10s timeout. Observed 2026-05-21 on S&P 500 large-caps (ABBV/ABT/ACN/
ADM) where the symbol is obviously valid yet every weekCandle call
timed out — that's rate-limit-induced packet drop, not "invalid ticker".

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

────────────────────────────────────────────────────────────────────────
Protective layers (added 2026-05-22 after the GH Actions cron started
hitting Naver rate-limit cascades that timed out the whole daily-scan
workflow — 75 min step ceiling exceeded):

  Layer 1 — Token bucket (NAVER_RPM, default 30 req/min). Cheap insurance
    against the burst pattern that triggers Naver's silent IP throttling.

  Layer 2 — Per-call jitter (NAVER_JITTER_MS, default 200-700ms). Avoids
    synchronous lock-step patterns that look bot-like to Naver's edge.

  Layer 3 — Exponential backoff (1s → 2s → 4s) on timeout, max 3 retries.
    Recovers when Naver hiccups for a single ticker without giving up.

  Layer 4 — Circuit breaker. After CB_THRESHOLD (default 5) consecutive
    failures we mark Naver "open" for CB_COOLDOWN (default 5 min) and
    fast-fail every call during that window. Callers (ingest_bars) can
    use is_circuit_open() to decide whether to skip-and-fallback (Stooq)
    without paying timeout cost per ticker.

All four layers are thread-safe (single module-level lock for the
counters; ThreadPoolExecutor-safe for KR's 12-worker pool though we
only use it sequentially in the US path today).
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
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


# ────────────────────────────────────────────────────────────────────────
# Protective layers — token bucket, jitter, backoff, circuit breaker
# ────────────────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Rate limit — capacity = burst size, refill drains it at RPM. 30/min ≈
# Naver's safe ceiling from Azure observed cron logs. Burst of 5 lets
# the very first few calls go through fast for low-volume contexts
# (single ad-hoc ticker analyze) while still capping sustained rate.
_NAVER_RPM = max(1, _env_int("NAVER_RPM", 30))
_TOKEN_BUCKET_CAP = max(1, _env_int("NAVER_BUCKET_CAP", 5))

_JITTER_MIN_MS = max(0, _env_int("NAVER_JITTER_MIN_MS", 200))
_JITTER_MAX_MS = max(_JITTER_MIN_MS, _env_int("NAVER_JITTER_MAX_MS", 700))

_BACKOFF_MAX_RETRIES = max(0, _env_int("NAVER_BACKOFF_RETRIES", 3))
_BACKOFF_BASE_S = max(0.1, _env_float("NAVER_BACKOFF_BASE_S", 1.0))

_CB_THRESHOLD = max(1, _env_int("NAVER_CB_THRESHOLD", 5))
_CB_COOLDOWN_S = max(1, _env_int("NAVER_CB_COOLDOWN_S", 300))

# Mutable state — all reads/writes through _lock.
_lock = threading.Lock()
_tokens = float(_TOKEN_BUCKET_CAP)
_last_refill = time.monotonic()
_consecutive_failures = 0
_circuit_open_until = 0.0   # monotonic timestamp; <= now means closed


def _acquire_token() -> None:
    """Block until a request token is available. Token bucket refills at
    _NAVER_RPM/60 tokens per second up to _TOKEN_BUCKET_CAP."""
    global _tokens, _last_refill
    while True:
        with _lock:
            now = time.monotonic()
            elapsed = now - _last_refill
            if elapsed > 0:
                _tokens = min(
                    float(_TOKEN_BUCKET_CAP),
                    _tokens + elapsed * (_NAVER_RPM / 60.0),
                )
                _last_refill = now
            if _tokens >= 1.0:
                _tokens -= 1.0
                return
            # Compute wait time for next whole token to refill.
            wait_s = max(0.05, (1.0 - _tokens) * (60.0 / _NAVER_RPM))
        time.sleep(wait_s)


def is_circuit_open() -> bool:
    """True iff the circuit breaker is currently open (Naver paused).
    Callers like ingest_bars can use this to decide whether to even try
    Naver, or skip directly to Stooq/secondary source."""
    with _lock:
        return time.monotonic() < _circuit_open_until


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    with _lock:
        _consecutive_failures = 0
        # First success after a half-open probe — fully close the circuit.
        _circuit_open_until = 0.0


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open_until
    with _lock:
        _consecutive_failures += 1
        if (
            _consecutive_failures >= _CB_THRESHOLD
            and _circuit_open_until <= time.monotonic()
        ):
            _circuit_open_until = time.monotonic() + _CB_COOLDOWN_S
            log.warning(
                "Naver circuit breaker OPEN after %d consecutive failures; "
                "cooling for %ds",
                _consecutive_failures,
                _CB_COOLDOWN_S,
            )


def _sleep_jitter() -> None:
    if _JITTER_MAX_MS <= 0:
        return
    ms = random.uniform(_JITTER_MIN_MS, _JITTER_MAX_MS)
    time.sleep(ms / 1000.0)


def reset_state_for_tests() -> None:
    """Used by tests to clear circuit / counters between cases. Not
    used in production code paths."""
    global _tokens, _last_refill, _consecutive_failures, _circuit_open_until
    with _lock:
        _tokens = float(_TOKEN_BUCKET_CAP)
        _last_refill = time.monotonic()
        _consecutive_failures = 0
        _circuit_open_until = 0.0


def _get_with_protection(url: str, params: dict) -> Optional[requests.Response]:
    """Issue a GET request guarded by all 4 protective layers.

    Returns the requests.Response on HTTP success (any status 2xx-5xx),
    None on network failure / timeout / circuit-open.
    """
    if is_circuit_open():
        log.debug("naver circuit open; fast-failing %s", url)
        return None

    for attempt in range(_BACKOFF_MAX_RETRIES + 1):
        _acquire_token()
        try:
            r = requests.get(
                url, params=params, headers=_HEADERS, timeout=_TIMEOUT,
            )
        except requests.Timeout:
            _record_failure()
            log.debug("naver timeout (attempt %d) %s", attempt + 1, url)
            if attempt < _BACKOFF_MAX_RETRIES and not is_circuit_open():
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
                continue
            return None
        except requests.RequestException as e:
            _record_failure()
            log.warning("naver fetch %s failed: %s", url, e)
            return None
        finally:
            _sleep_jitter()

        # 4xx is "valid ticker doesn't exist on this exchange" or "bad
        # request" — NOT a Naver outage. Count as success for circuit
        # purposes (caller decides what to do with the 404).
        if 200 <= r.status_code < 500:
            _record_success()
            return r
        # 5xx — record failure and back off.
        _record_failure()
        if attempt < _BACKOFF_MAX_RETRIES and not is_circuit_open():
            time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
            continue
        return r


def _fetch(symbol: str, period_type: str, years: int) -> Optional[pd.DataFrame]:
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=int(years * 365) + 30)
    params = {
        "startDateTime": start.strftime("%Y%m%d%H%M%S"),
        "endDateTime": end.strftime("%Y%m%d%H%M%S"),
        "periodType": period_type,
    }
    r = _get_with_protection(f"{_BASE}/{symbol}", params)
    if r is None:
        return None
    if r.status_code != 200:
        log.debug("naver %s/%s HTTP %s", symbol, period_type, r.status_code)
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
    # Once circuit opens mid-loop, stop trying remaining suffixes — they'd
    # all fast-fail anyway and the caller wants to fall back to Stooq.
    for suffix in (".O", ".K", ".A"):
        if is_circuit_open():
            return None
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
