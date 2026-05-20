"""One-shot backfill — fetch 2020-04 ~ 2021-04 KR bars for all active
tickers so 240MA analysis works on more than 80% of stocks.

Why this exists: ingest_bars normally fetches 5 years rolling. Our
earliest bar is 2021-04-23 (4y 1m ago) — 240 weekly bars (4.6 years)
not quite reachable. This script reaches one year further back so
~95% of tickers have a full 240-week window.

After running this once:
  - retention.py should keep 6-year window (will be updated)
  - normal ingest_bars cron resumes 5-year incremental fetch

Run standalone:
    python scripts/backfill_bars_history.py             # all KR active
    python scripts/backfill_bars_history.py --limit 50  # debug
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402
from app.db.ingest_bars import (  # noqa: E402
    fetch_kr_ticker, active_tickers,
)

log = logging.getLogger("backfill_bars")


def _upsert_weekly_monthly(rows):
    """Same upsert path as ingest_bars but no FLUSH chunking
    (we'll batch here)."""
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO bars (ticker, granularity, bar_date, open, high,
                                  low, close, adj_close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, granularity, bar_date) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    adj_close = EXCLUDED.adj_close,
                    volume = EXCLUDED.volume
                """,
                rows,
            )
    return len(rows)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None,
                   help="limit to N tickers (debug)")
    p.add_argument("--workers", type=int, default=12)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Backfill window: from 2020-04 (6 years ago) up to 2021-05 (just
    # past the existing earliest bar 2021-04-23). One-year window only —
    # FDR fetch is bounded.
    today = date.today()
    start = today - timedelta(days=6 * 365 + 30)
    end = today - timedelta(days=4 * 365)  # leave 4 years to existing data
    log.info("backfill window: %s to %s", start, end)

    # All KR active tickers (KOSPI + KOSDAQ)
    tickers = []
    for market in ("KOSPI", "KOSDAQ"):
        rows = active_tickers(market)
        tickers.extend([t for t, _ in rows])
    if args.limit:
        tickers = tickers[: args.limit]
    log.info("backfilling %d KR tickers", len(tickers))

    t0 = time.time()
    n_total = 0
    n_errors = 0
    buf = []
    FLUSH_EVERY = 2000
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        # fetch_kr_ticker handles W + M resampling automatically.
        futures = {
            pool.submit(fetch_kr_ticker, t, start, end): t
            for t in tickers
        }
        for i, fut in enumerate(as_completed(futures), 1):
            t = futures[fut]
            try:
                rows = fut.result()
                buf.extend(rows)
            except Exception as e:
                log.warning("ticker=%s error: %s", t, e)
                n_errors += 1
            if len(buf) >= FLUSH_EVERY:
                n_total += _upsert_weekly_monthly(buf)
                buf = []
            if i % 200 == 0:
                log.info("  [%d/%d] inserted=%d, errors=%d, elapsed=%.0fs",
                         i, len(tickers), n_total, n_errors, time.time() - t0)
    if buf:
        n_total += _upsert_weekly_monthly(buf)
    log.info("done in %.0fs: %d rows backfilled, %d errors",
             time.time() - t0, n_total, n_errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
