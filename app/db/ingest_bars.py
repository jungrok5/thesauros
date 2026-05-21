"""Refresh OHLCV bars in Supabase `bars`.

Weekly + monthly only — the daily-storage era ended with migration 021.
Book strategy is swing trading, and the engine's primary signals are
월봉 240MA + 월봉/주봉 10MA. Daily bars added storage cost (Supabase Free
500MB ceiling) without analysis value.

Per market:

  KR (KOSPI / KOSDAQ): FinanceDataReader pulls 5 years of daily candles
    per ticker (threaded), then resamples in-memory to W-FRI (week-ending
    Friday) and M (month-ending last business day) before a single
    UPSERT.

  US (NASDAQ / NYSE / ...): Naver Finance weekCandle (~110 weekly bars
    ≈ 2 years) and monthCandle (~110 monthly bars ≈ 9 years, capped at
    5y by retention). yfinance is blocked on cloud runners — Naver works.
    Watchlist-driven by default to keep storage proportional to usage.

Idempotent: re-running on the same week is a near no-op (UPSERT rewrites
identical rows). For tickers with zero bars we backfill ~5 years.

Usage:
    python -m app.db.ingest_bars                # all markets (KR full, US watchlist)
    python -m app.db.ingest_bars --markets KOSPI
    python -m app.db.ingest_bars --workers 16   # threadpool size for KR
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_bars")

KR_MARKETS = ("KOSPI", "KOSDAQ")
US_MARKETS = ("NASDAQ", "NYSE", "AMEX", "ARCA", "BATS")

YEARS_HISTORY = 5      # KR FDR fetch window; US Naver is capped to its own.


# ────────────────────────────────────────────────────────────────────────
# DB helpers
# ────────────────────────────────────────────────────────────────────────

def active_tickers(market: Optional[str] = None) -> List[Tuple[str, str]]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            if market:
                cur.execute(
                    "SELECT ticker, market FROM tickers "
                    "WHERE is_active = true AND market = %s",
                    (market.upper(),),
                )
            else:
                cur.execute(
                    "SELECT ticker, market FROM tickers WHERE is_active = true"
                )
            return list(cur.fetchall())


def watchlist_tickers() -> List[Tuple[str, str]]:
    """Tickers in any user's watchlist (with market). Used to pick up
    user-chosen out-of-default-universe names so scan_daily later finds
    bars in DB."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT t.ticker, t.market "
                "  FROM watchlist w "
                "  JOIN tickers t ON t.ticker = w.ticker "
                " WHERE t.is_active = true"
            )
            return list(cur.fetchall())


def upsert_bars(rows: Sequence[Tuple[Any, ...]]) -> int:
    """Upsert (ticker, granularity, bar_date, open, high, low, close,
    adj_close, volume) — 9 columns."""
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO bars
                  (ticker, granularity, bar_date, open, high, low, close,
                   adj_close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, granularity, bar_date) DO UPDATE SET
                  open      = EXCLUDED.open,
                  high      = EXCLUDED.high,
                  low       = EXCLUDED.low,
                  close     = EXCLUDED.close,
                  adj_close = EXCLUDED.adj_close,
                  volume    = EXCLUDED.volume
                """,
                rows,
            )
    return len(rows)


# ────────────────────────────────────────────────────────────────────────
# Resampling helper
# ────────────────────────────────────────────────────────────────────────

def _resample_daily_to_rows(
    ticker: str, daily_df: pd.DataFrame,
) -> List[Tuple[Any, ...]]:
    """Take a per-ticker daily OHLCV DataFrame (date-indexed or columned),
    resample to W-FRI and M-end, return rows ready for `upsert_bars`.

    Skips weeks/months with zero observed bars. Volumes sum within the
    period; OHLC follows pandas standard W resampling (open=first,
    high=max, low=min, close=last).
    """
    if daily_df is None or daily_df.empty:
        return []

    df = daily_df.copy()
    if "date" not in df.columns:
        df = df.reset_index()
        # pandas may have called the index either "Date", "date", or "index"
        first = df.columns[0]
        if first != "date":
            df = df.rename(columns={first: "date"})

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # "ME" = month-end (pandas 2.2+ renamed "M" → "ME" with a deprecation
    # warning; "W-FRI" stays as-is).
    rule_map = {"W": "W-FRI", "M": "ME"}
    agg = {
        "open": "first", "high": "max", "low": "min", "close": "last",
        "adj_close": "last", "volume": "sum",
    }
    # Coerce numeric, fill missing volume
    for c in ("open", "high", "low", "close", "adj_close"):
        if c not in df.columns:
            df[c] = pd.NA
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    out: List[Tuple[Any, ...]] = []
    for granularity, rule in rule_map.items():
        rs = df.resample(rule).agg(agg).dropna(subset=["close"])
        for ts, row in rs.iterrows():
            close = _num(row["close"])
            if close is None or close == 0:
                continue
            adj = _num(row.get("adj_close")) or close
            out.append((
                ticker,
                granularity,
                ts.date(),
                _num(row.get("open")),
                _num(row.get("high")),
                _num(row.get("low")),
                close,
                adj,
                _int(row.get("volume")),
            ))
    return out


# ────────────────────────────────────────────────────────────────────────
# KR fetcher — FinanceDataReader → resample W + M
# ────────────────────────────────────────────────────────────────────────

def _kr_code(ticker: str) -> Optional[str]:
    if "." not in ticker:
        return None
    code, suffix = ticker.split(".", 1)
    if suffix in ("KS", "KQ") and code.isdigit() and len(code) == 6:
        return code
    return None


def fetch_kr_ticker(ticker: str, start: date, end: date) -> List[Tuple[Any, ...]]:
    """Fetch a single KR ticker's daily history via FDR, return
    resampled weekly + monthly rows ready for upsert."""
    import FinanceDataReader as fdr
    code = _kr_code(ticker)
    if not code:
        return []
    try:
        df = fdr.DataReader(code, start.isoformat(), end.isoformat())
    except Exception as e:
        log.debug("fdr %s: %s", ticker, e)
        return []
    if df is None or df.empty:
        return []
    df = df.reset_index().rename(columns={
        "Date": "date",
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df["adj_close"] = df["close"]   # KR markets adjust in place
    # FDR returns a "거래정지" placeholder row for non-trading days on
    # the symbol — OHLV all zero, volume zero, only Close set (carries
    # forward the prior close as a reference price). Persisting these
    # poisons later analysis: 52w_low becomes 0, candle wicks become
    # NaN/Inf, volume cases see every bar as "거래량 폭증". Drop them
    # at the source so the weekly/monthly resample produces clean OHLC.
    suspended = (
        (df["open"].fillna(0) == 0)
        & (df["high"].fillna(0) == 0)
        & (df["low"].fillna(0) == 0)
        & (df["volume"].fillna(0) == 0)
    )
    if suspended.any():
        log.debug("fdr %s: dropping %d suspended-day rows", ticker, int(suspended.sum()))
        df = df.loc[~suspended].copy()
    if df.empty:
        return []
    return _resample_daily_to_rows(ticker, df)


# ────────────────────────────────────────────────────────────────────────
# US fetcher — Naver weekCandle + monthCandle (no resample needed)
# ────────────────────────────────────────────────────────────────────────

def _rows_from_df(ticker: str, granularity: str, df) -> List[Tuple[Any, ...]]:
    out: List[Tuple[Any, ...]] = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        close = _num(row["close"])
        if close is None or close == 0:
            continue
        out.append((
            ticker, granularity, row["date"].date(),
            _num(row.get("open")), _num(row.get("high")),
            _num(row.get("low")), close,
            _num(row.get("adj_close")) or close,
            _int(row.get("volume")),
        ))
    return out


def fetch_us_ticker(ticker: str) -> List[Tuple[Any, ...]]:
    """Fetch US weekly + monthly bars. Naver is the primary source
    (volume figures match what KR retail tools display, calibrating the
    engine's volume signals). Stooq is fallback for when Naver is
    blocked or returns empty — coverage is narrower but it doesn't get
    cloud-IP rate-limited the way Naver does.

    Naver caps each response at 110 rows (~2y weekly + ~9y monthly).
    Stooq returns full history (typically 5+ years). Retention later
    caps monthly at 5y per policy."""
    from app.data import naver_bars
    from app.data import stooq

    # If Naver's circuit breaker is already open from prior failures in
    # this run, skip straight to Stooq — pays no timeout cost.
    skip_naver = naver_bars.is_circuit_open()
    out: List[Tuple[Any, ...]] = []

    wdf = None if skip_naver else naver_bars.fetch_weekly(ticker, years=YEARS_HISTORY)
    if wdf is None or wdf.empty:
        wdf = stooq.fetch_weekly(ticker, years=YEARS_HISTORY)
        if wdf is not None and not wdf.empty:
            log.debug("stooq fallback weekly %s rows=%d", ticker, len(wdf))
    out.extend(_rows_from_df(ticker, "W", wdf))

    mdf = None if skip_naver else naver_bars.fetch_monthly(ticker, years=YEARS_HISTORY)
    if mdf is None or mdf.empty:
        mdf = stooq.fetch_monthly(ticker, years=YEARS_HISTORY)
        if mdf is not None and not mdf.empty:
            log.debug("stooq fallback monthly %s rows=%d", ticker, len(mdf))
    out.extend(_rows_from_df(ticker, "M", mdf))

    return out


# ────────────────────────────────────────────────────────────────────────
# Type coercion
# ────────────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        f = float(v)
        return f if pd.notna(f) else None
    except Exception:
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return None if n is None else int(n)


# ────────────────────────────────────────────────────────────────────────
# Driver
# ────────────────────────────────────────────────────────────────────────

def run_kr(market: str, today: date, workers: int) -> int:
    rows = active_tickers(market)
    tickers = [t for t, _ in rows]
    for t, m in watchlist_tickers():
        if m == market and t not in tickers:
            tickers.append(t)
    if not tickers:
        log.info("%s: no active tickers", market)
        return 0

    start = today - timedelta(days=YEARS_HISTORY * 365 + 30)
    log.info("%s: fetching %d ticker(s), %s -> %s",
             market, len(tickers), start, today)

    n_total = 0
    n_errors = 0
    buf: List[Tuple[Any, ...]] = []
    FLUSH_EVERY = 2000
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_kr_ticker, t, start, today): t
                for t in tickers
            }
            for i, fut in enumerate(as_completed(futures), 1):
                t = futures[fut]
                try:
                    rows = fut.result()
                    buf.extend(rows)
                except Exception as e:
                    n_errors += 1
                    log.debug("fetch %s: %s", t, e)
                if len(buf) >= FLUSH_EVERY:
                    n_total += upsert_bars(buf)
                    buf.clear()
                if i % 200 == 0:
                    log.info("  %s [%d/%d] rows=%d errors=%d",
                             market, i, len(tickers), n_total + len(buf), n_errors)
    finally:
        if buf:
            n_total += upsert_bars(buf)
            buf.clear()
    log.info("  %s done: rows=%d errors=%d", market, n_total, n_errors)
    return n_total


def run_us(watchlist_only: bool = True) -> int:
    """Ingest US bars from Naver. Sequential — Naver is rate-friendly
    but we don't push it. By default watchlist-only (cron path) since
    US is not yet in the default scan universe."""
    if watchlist_only:
        wl_us = [t for t, m in watchlist_tickers() if m in US_MARKETS]
        us_rows = wl_us
    else:
        us_rows = [t for t, m in active_tickers() if m in US_MARKETS]

    if not us_rows:
        log.info("US: no tickers to fetch")
        return 0

    log.info("US: fetching %d ticker(s) via Naver", len(us_rows))
    buf: List[Tuple[Any, ...]] = []
    n_errors = 0
    for t in us_rows:
        try:
            buf.extend(fetch_us_ticker(t))
        except Exception as e:
            n_errors += 1
            log.warning("naver fetch %s: %s", t, e)
        if len(buf) >= 2000:
            upsert_bars(buf)
            buf.clear()
    n = upsert_bars(buf)
    log.info("  US done: rows=%d errors=%d", n, n_errors)
    return n


def run_one(ticker: str) -> int:
    """Single-ticker ingest, used by analyze-ticker.yml so a freshly
    watchlisted name has both bars (for /api/chart) and analyze_results
    (for the analysis view) populated within one workflow run.
    Auto-routes KR vs US by ticker suffix."""
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        today = date.today()
        start = today - timedelta(days=YEARS_HISTORY * 365 + 30)
        rows = fetch_kr_ticker(t, start, today)
    else:
        rows = fetch_us_ticker(t)
    n = upsert_bars(rows)
    log.info("  one-shot %s: rows=%d", t, n)
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+",
                   default=["KOSPI", "KOSDAQ"],
                   help="markets to ingest (default: KOSPI KOSDAQ; US is "
                        "user-watchlist-driven)")
    p.add_argument("--tickers", nargs="+",
                   help="ingest only these specific tickers (one-shot mode "
                        "for analyze-ticker.yml watchlist dispatch)")
    p.add_argument("--workers", type=int, default=12,
                   help="thread pool size for KR per-ticker fetch")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    t0 = time.time()
    n_total = 0

    if args.tickers:
        # One-shot mode — auto-route KR vs US per ticker, ignore --markets.
        for tk in args.tickers:
            try:
                n_total += run_one(tk)
            except Exception as e:
                log.error("one-shot %s failed: %s", tk, e)
        log.info("done in %.1fs: total rows upserted=%d",
                 time.time() - t0, n_total)
        return 0

    markets = {m.upper() for m in args.markets} if args.markets else None
    today = date.today()

    for m in KR_MARKETS:
        if markets and m not in markets:
            continue
        try:
            n_total += run_kr(m, today, args.workers)
        except Exception as e:
            log.error("%s ingest failed: %s", m, e)

    # US ingest:
    #   - explicit --markets US* → full US universe (heavy, manual only)
    #   - default cron (markets={KOSPI,KOSDAQ}) → watchlist-only path so
    #     user-added US tickers still get fresh bars + analysis. This
    #     was the missing branch — the old "if not markets or markets &
    #     US_MARKETS" guard skipped US entirely under the cron's default
    #     KOSPI/KOSDAQ filter, leaving the 6,870 US universe at 0 rows.
    if markets and (markets & set(US_MARKETS)):
        try:
            n_total += run_us(watchlist_only=False)
        except Exception as e:
            log.error("US ingest (universe) failed: %s", e)
    else:
        try:
            n_total += run_us(watchlist_only=True)
        except Exception as e:
            log.error("US ingest (watchlist) failed: %s", e)

    log.info("done in %.1fs: total rows upserted=%d",
             time.time() - t0, n_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
