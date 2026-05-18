"""Refresh OHLCV bars in Supabase `bars_daily`.

Incremental fetcher used by the daily-scan cron.

  - KR (KOSPI/KOSDAQ): FinanceDataReader per-ticker, threaded.
    pykrx ships with mojibake column headers that break on every
    install we've tested, so FDR is the canonical KR source here.
  - US (NASDAQ/NYSE/...): yfinance batched `yf.download` in 150-ticker
    groups (S&P 500 only by default — matches scan_daily).

Strategy: per-market we read `MAX(bar_date)` already in the table, then
fetch from `latest+1` to today and UPSERT on (ticker, bar_date).
Re-runs on the same day are a near no-op (UPDATE rewrites identical
rows). For tickers with zero bars we backfill `--backfill-days` (default 7).

Usage:
    python -m app.db.ingest_bars_daily                # all markets, incremental
    python -m app.db.ingest_bars_daily --markets KOSPI
    python -m app.db.ingest_bars_daily --backfill-days 30
    python -m app.db.ingest_bars_daily --workers 16   # threadpool size
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

log = logging.getLogger("ingest_bars_daily")

KR_MARKETS = ("KOSPI", "KOSDAQ")
US_MARKETS = ("NASDAQ", "NYSE", "AMEX", "ARCA", "BATS")


# ────────────────────────────────────────────────────────────────────────
# DB helpers
# ────────────────────────────────────────────────────────────────────────

def latest_bar_date_per_ticker(tickers: Sequence[str]) -> Dict[str, date]:
    """{ticker: MAX(bar_date)}. Tickers with no bars are absent."""
    if not tickers:
        return {}
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, MAX(bar_date) FROM bars_daily "
                "WHERE ticker = ANY(%s) GROUP BY ticker",
                (list(tickers),),
            )
            return {r[0]: r[1] for r in cur.fetchall()}


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
    """Tickers any user has added to a watchlist, with their market.
    Lets the bars ingest pick up user-chosen out-of-default-universe names
    (e.g. NASDAQ mid-caps) so scan_daily later finds bars in DB."""
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
    """Upsert (ticker, bar_date, open, high, low, close, adj_close, volume)."""
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO bars_daily
                  (ticker, bar_date, open, high, low, close, adj_close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, bar_date) DO UPDATE SET
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
# KR fetcher — FinanceDataReader per-ticker
# ────────────────────────────────────────────────────────────────────────

def _kr_code(ticker: str) -> Optional[str]:
    # "005380.KS" / "005380.KQ" → "005380"
    if "." not in ticker:
        return None
    code, suffix = ticker.split(".", 1)
    if suffix in ("KS", "KQ") and code.isdigit() and len(code) == 6:
        return code
    return None


def fetch_kr_ticker(ticker: str, start: date, end: date) -> List[Tuple[Any, ...]]:
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
    out: List[Tuple[Any, ...]] = []
    for ts, row in df.iterrows():
        bd = ts.date() if hasattr(ts, "date") else ts
        c = _num(row.get("Close"))
        if c is None or c == 0:
            continue
        out.append((
            ticker, bd,
            _num(row.get("Open")),
            _num(row.get("High")),
            _num(row.get("Low")),
            c,
            c,                      # adj_close = close (KR markets adjust in place)
            _int(row.get("Volume")),
        ))
    return out


# ────────────────────────────────────────────────────────────────────────
# US fetcher — yfinance batched
# ────────────────────────────────────────────────────────────────────────

def fetch_us_batch(tickers: Sequence[str], start: date, end: date,
                   chunk: int = 150) -> List[Tuple[Any, ...]]:
    if not tickers:
        return []
    import yfinance as yf
    out: List[Tuple[Any, ...]] = []
    end_exclusive = end + timedelta(days=1)
    for i in range(0, len(tickers), chunk):
        batch = list(tickers[i:i + chunk])
        try:
            df = yf.download(
                tickers=" ".join(batch),
                start=start.isoformat(),
                end=end_exclusive.isoformat(),
                progress=False,
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as e:
            log.warning("yfinance batch [%d:%d]: %s", i, i + chunk, e)
            continue
        if df is None or df.empty:
            continue
        for t in batch:
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    if t not in df.columns.get_level_values(0):
                        continue
                    sub = df[t]
                else:
                    sub = df
            except Exception:
                continue
            for ts, row in sub.iterrows():
                bd = ts.date() if hasattr(ts, "date") else ts
                close = _num(row.get("Close"))
                if close is None or close == 0:
                    continue
                out.append((
                    t, bd,
                    _num(row.get("Open")),
                    _num(row.get("High")),
                    _num(row.get("Low")),
                    close,
                    _num(row.get("Adj Close")) or close,
                    _int(row.get("Volume")),
                ))
        time.sleep(0.5)   # friendly to yfinance
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

def run_kr(market: str, today: date, backfill_days: int, workers: int) -> int:
    rows = active_tickers(market)
    tickers = [t for t, _ in rows]
    # Pull in user-watchlisted KR tickers too — defensive, since the
    # `tickers` master usually already includes them.
    for t, m in watchlist_tickers():
        if m == market and t not in tickers:
            tickers.append(t)
    if not tickers:
        log.info("%s: no active tickers", market)
        return 0
    last = latest_bar_date_per_ticker(tickers)
    fallback_start = today - timedelta(days=backfill_days)

    # Per ticker, decide its start date (last+1 or fallback for new ones).
    plan: List[Tuple[str, date]] = []
    for t in tickers:
        last_d = last.get(t)
        start = last_d + timedelta(days=1) if last_d else fallback_start
        if start <= today:
            plan.append((t, start))
    if not plan:
        log.info("%s: %d tickers, all up to date", market, len(tickers))
        return 0

    log.info("%s: fetching %d ticker(s), today=%s",
             market, len(plan), today)
    n_total = 0
    n_errors = 0
    buf: List[Tuple[Any, ...]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_kr_ticker, t, start, today): t
                for t, start in plan
            }
            FLUSH_EVERY = 1000
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
                             market, i, len(plan), n_total + len(buf), n_errors)
    finally:
        # Even on KeyboardInterrupt / OOM / pool-shutdown error, persist
        # whatever the workers have already produced so we never silently
        # drop up to FLUSH_EVERY rows of work.
        if buf:
            n_total += upsert_bars(buf)
            buf.clear()
    log.info("  %s done: rows=%d errors=%d", market, n_total, n_errors)
    return n_total


def run_us(today: date, backfill_days: int, sp500_only: bool,
           watchlist_only: bool = False) -> int:
    """Ingest US bars. By default (cron path), watchlist_only is True —
    we only fetch US tickers that at least one user has watchlisted,
    NOT the full S&P 500. This keeps DB footprint proportional to actual
    usage."""
    if watchlist_only:
        wl_us = [t for t, m in watchlist_tickers() if m in US_MARKETS]
        if not wl_us:
            log.info("US: no watchlisted US tickers — skipping")
            return 0
        us_rows = wl_us
    else:
        us_rows = [t for t, m in active_tickers() if m in US_MARKETS]
        if sp500_only:
            try:
                from app.data.universe import fetch_sp500_table
                sp = set(fetch_sp500_table()["ticker"].tolist())
                us_rows = [t for t in us_rows if t in sp]
            except Exception as e:
                log.warning("S&P 500 filter failed: %s — using full US set", e)
        if not us_rows:
            return 0
    last = latest_bar_date_per_ticker(us_rows)
    earliest = min(last.values()) if last and len(last) == len(us_rows) else None
    start = (
        earliest + timedelta(days=1) if earliest
        else today - timedelta(days=backfill_days)
    )
    if start > today:
        log.info("US: up to date (oldest=%s)", earliest)
        return 0
    log.info("US: fetching %s → %s for %d ticker(s)",
             start, today, len(us_rows))
    rows = fetch_us_batch(us_rows, start, today)
    n = upsert_bars(rows)
    log.info("  US done: rows=%d", n)
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+",
                   default=["KOSPI", "KOSDAQ"],
                   help="markets to ingest (default: KOSPI KOSDAQ; US is "
                        "user-watchlist-driven and uses the same FDR/yf path)")
    p.add_argument("--backfill-days", type=int, default=7,
                   help="fallback window when a ticker has no rows at all")
    p.add_argument("--workers", type=int, default=12,
                   help="thread pool size for KR per-ticker fetch")
    p.add_argument("--sp500-only", action="store_true", default=True,
                   help="confine US universe to S&P 500 (default: on)")
    p.add_argument("--no-sp500-only", dest="sp500_only", action="store_false")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    markets = {m.upper() for m in args.markets} if args.markets else None
    today = date.today()
    t0 = time.time()

    n_total = 0
    if not markets or markets & set(KR_MARKETS):
        for m in KR_MARKETS:
            if markets and m not in markets:
                continue
            try:
                n_total += run_kr(m, today, args.backfill_days, args.workers)
            except Exception as e:
                log.error("%s ingest failed: %s", m, e)

    # US: by default we only ingest watchlisted tickers (site primary
    # use case = KR). Explicit --markets including US disables this.
    run_us_now = bool(markets and (markets & set(US_MARKETS)))
    if not markets:
        # Default cron path — watchlist-driven US only.
        run_us_now = True
    if run_us_now:
        try:
            watchlist_only = not markets   # default mode → watchlist-only
            n_total += run_us(today, args.backfill_days, args.sp500_only,
                              watchlist_only=watchlist_only)
        except Exception as e:
            log.error("US ingest failed: %s", e)

    log.info("done in %.1fs: total rows upserted=%d",
             time.time() - t0, n_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
