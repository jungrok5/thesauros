"""Initial backfill of local DuckDB bars store (2008-now, KOSPI+KOSDAQ).

Performance design:
  - **Parallel FDR fetch**: ThreadPoolExecutor, default 12 workers
    (FDR is IO-bound — most time in HTTP).
  - **Batch INSERT to DuckDB**: accumulate fetched rows per ticker and
    write in chunks (FLUSH_EVERY tickers) rather than per-row.
  - **Resumable**: ingest_log tracks completion. Re-running skips
    tickers already covered by --skip-existing (default ON).
  - **Per-ticker fault isolation**: one ticker's exception doesn't
    cascade — logged and counted.

Time budget (estimates, KOSPI+KOSDAQ ≈ 2700 tickers, 17 years):
  - 12 workers × ~0.5-2s/ticker (FDR API) → 225-900s pure fetch
  - DuckDB inserts ≈ 30s total (batched)
  - Total: **~5-20 minutes** depending on FDR responsiveness

Usage:
    python -m scripts.build_local_bars                 # full universe
    python -m scripts.build_local_bars --limit 20      # smoke
    python -m scripts.build_local_bars --start 2008-01-01 --end 2026-05-23
    python -m scripts.build_local_bars --tickers 005930.KS 035720.KS
    python -m scripts.build_local_bars --resume        # skip already-ingested

Resume policy:
  By default we SKIP tickers already in `ingest_log`. Use --refresh to
  re-fetch (overwrites prior rows via UPSERT in `bars` PK).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from app.backtest.local_store import (    # noqa: E402
    connect, list_ingested_tickers, record_ingest, store_stats, upsert_bars,
)
from app.db.ingest_bars import (          # noqa: E402
    active_tickers, fetch_kr_ticker, _resample_daily_to_rows,
)

log = logging.getLogger("build_local_bars")


def _fetch_yfinance(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch via yfinance — depth back to 2000 for most KR tickers.

    Returns daily DataFrame with columns: open, high, low, close,
    adj_close, volume. yfinance's `Close` is split/dividend-adjusted
    already (no separate adj_close column in modern yf).

    Returns empty df if ticker unavailable.
    """
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start.isoformat(), end=end.isoformat(),
                       auto_adjust=False, repair=False)
    except Exception as e:
        log.debug("yfinance %s: %s", ticker, e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    # yfinance columns: Open, High, Low, Close, Adj Close, Volume,
    # Dividends, Stock Splits. Normalize.
    df = df.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    # tz-naive (yfinance returns tz-aware datetimes for KR — strip)
    if isinstance(df["date"].dtype, pd.DatetimeTZDtype):
        df["date"] = df["date"].dt.tz_convert(None)
    keep_cols = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    # Drop suspended-day placeholder rows (OHLV = 0).
    suspended = (
        (df["open"].fillna(0) == 0)
        & (df["high"].fillna(0) == 0)
        & (df["low"].fillna(0) == 0)
        & (df["volume"].fillna(0) == 0)
    )
    if suspended.any():
        df = df.loc[~suspended].copy()
    return df


def _resolve_universe(args: argparse.Namespace) -> List[str]:
    if args.tickers:
        return list(args.tickers)
    markets = (
        ["KOSPI"] if args.market == "KOSPI"
        else ["KOSDAQ"] if args.market == "KOSDAQ"
        else ["KOSPI", "KOSDAQ"]
    )
    tickers = []
    for m in markets:
        rows = active_tickers(m)
        tickers.extend([t for t, _ in rows])
    tickers = sorted(set(tickers))
    if args.limit:
        tickers = tickers[: args.limit]
    return tickers


def _fetch_one_ticker(ticker: str, start: date, end: date,
                      source: str = "yfinance") -> pd.DataFrame:
    """Fetch ONE ticker, resample to W + M, return wide DataFrame
    with `granularity` column.

    source:
      - 'yfinance' (default, deep history back to 2000)
      - 'fdr'     (shallower, 2014~)
    """
    if source == "yfinance":
        daily = _fetch_yfinance(ticker, start, end)
    else:
        # fdr fallback path — kept for parity / when yfinance throttled.
        rows = fetch_kr_ticker(ticker, start, end)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=[
            "ticker", "granularity", "bar_date",
            "open", "high", "low", "close", "adj_close", "volume",
        ])
        return df
    if daily.empty:
        return pd.DataFrame()
    # _resample_daily_to_rows returns the same tuple shape as the
    # legacy fetch_kr_ticker path — reshape to DataFrame.
    rows = _resample_daily_to_rows(ticker, daily)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "ticker", "granularity", "bar_date",
        "open", "high", "low", "close", "adj_close", "volume",
    ])
    return df


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", default="2008-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--tickers", nargs="+", default=None,
                   help="explicit ticker list (overrides market)")
    p.add_argument("--market", choices=["KOSPI", "KOSDAQ", "BOTH"],
                   default="BOTH")
    p.add_argument("--limit", type=int, default=None,
                   help="cap ticker count after market filter (debug)")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--flush-every", type=int, default=20,
                   help="flush DuckDB after every N completed tickers")
    p.add_argument("--refresh", action="store_true",
                   help="re-fetch tickers already in ingest_log "
                        "(default: skip them)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    universe = _resolve_universe(args)
    log.info("backfill window %s → %s, %d ticker(s), %d workers",
             start, end, len(universe), args.workers)

    # Open DuckDB once for the entire run — writes serialized through it.
    with connect() as conn:
        if not args.refresh:
            already = {
                r[0] for r in conn.execute(
                    "SELECT ticker FROM ingest_log"
                ).fetchall()
            }
            skipped = [t for t in universe if t in already]
            universe = [t for t in universe if t not in already]
            if skipped:
                log.info("skipping %d ticker(s) already in ingest_log "
                         "(use --refresh to re-fetch)", len(skipped))
        if not universe:
            log.info("nothing to do — all tickers already ingested")
            stats = store_stats()
            log.info("store stats: %s", stats)
            return 0

        t0 = time.time()
        total_rows = 0
        n_errors = 0
        completed = 0
        buf: List[pd.DataFrame] = []
        buf_log: List[tuple] = []   # (ticker, n_rows, error_count)

        def _flush() -> None:
            nonlocal total_rows, buf, buf_log
            if not buf:
                return
            # One COPY-style write per ticker — DuckDB INSERT OR REPLACE
            # handles dupes via PK.
            for df, (t, n, errs) in zip(buf, buf_log):
                if df is not None and not df.empty:
                    upsert_bars(conn, t, df)
                record_ingest(
                    conn, t, source="fdr",
                    range_start=start, range_end=end,
                    n_bars=n, n_errors=errs,
                )
                total_rows += n
            buf = []
            buf_log = []

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_fetch_one_ticker, t, start, end): t
                for t in universe
            }
            for fut in as_completed(futures):
                ticker = futures[fut]
                completed += 1
                try:
                    df = fut.result()
                    n = len(df)
                    buf.append(df)
                    buf_log.append((ticker, n, 0))
                except Exception as e:
                    log.warning("ticker=%s fetch error: %s", ticker, e)
                    n_errors += 1
                    buf.append(None)
                    buf_log.append((ticker, 0, 1))
                if completed % args.flush_every == 0:
                    _flush()
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed > 0 else 0
                    remain = (len(universe) - completed) / rate if rate > 0 else 0
                    log.info("[%d/%d] %.0fs elapsed, %d rows total, "
                             "%d errors, ~%.0fs remain",
                             completed, len(universe), elapsed,
                             total_rows, n_errors, remain)
        _flush()

        elapsed = time.time() - t0
        log.info("done in %.0fs: %d ticker(s), %d rows, %d errors",
                 elapsed, len(universe), total_rows, n_errors)

    stats = store_stats()
    log.info("store stats: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
