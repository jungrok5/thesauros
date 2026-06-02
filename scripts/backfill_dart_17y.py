"""R13 — DART 17-year fundamentals backfill.

Calls ingest_company(corp_code, stock_code, years=range(2009, 2025))
for every KR ticker with a DART corp_code mapping.

Persistence: writes directly to Supabase fundamentals (PK
(ticker, concept, fy)). Idempotent — ON CONFLICT updates.

Rate limit: DART free tier ~1000 calls/hour. We use ThreadPoolExecutor
with workers=8 (DART tolerates concurrent reads). Per-ticker cost:
~16 years × ~8 concepts = ~128 calls (but ingest_company batches them
into ~16 API calls). ~2,700 tickers × 16 calls = ~43k calls.

@ 1000 calls/hour with workers=8 → ~5-6 hours steady state, plus
retries. Budget: overnight.

Run:
  python scripts/backfill_dart_17y.py             # full 17y backfill
  python scripts/backfill_dart_17y.py --limit 50  # smoke test
  python scripts/backfill_dart_17y.py --from-year 2009 --to-year 2024
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from app.data.ingest_dart import (
    ingest_company, fetch_corp_code_map,
)
from app.db import get_conn


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("dart_backfill")


def fetch_target_tickers() -> set:
    """All currently-tracked KR tickers (active + delisted)."""
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT ticker FROM tickers "
            "WHERE market = ANY(ARRAY['KOSPI','KOSDAQ'])"
        )
        return {r[0] for r in cur.fetchall()}


def worker(corp_code: str, stock_code: str, years: list) -> tuple:
    try:
        n = ingest_company(corp_code, stock_code, years)
        return (stock_code, n, None)
    except Exception as e:
        return (stock_code, 0, str(e)[:80])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2009)
    ap.add_argument("--to-year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    years = list(range(args.from_year, args.to_year + 1))
    log.info("DART backfill years=%s", years)

    cmap = fetch_corp_code_map()
    log.info("corp_code map: %d entries", len(cmap))
    cmap = cmap[cmap["stock_code"].astype(str).str.match(r"^\d{6}$")]
    log.info("  filtered to 6-digit stock_codes: %d", len(cmap))

    target_tickers = fetch_target_tickers()
    log.info("KR universe: %d tickers", len(target_tickers))

    # Restrict corp_codes to those mapped to a tracked ticker
    rows = []
    for _, r in cmap.iterrows():
        sc = r["stock_code"]
        if f"{sc}.KS" in target_tickers or f"{sc}.KQ" in target_tickers:
            rows.append((r["corp_code"], sc))
    if args.limit:
        rows = rows[: args.limit]
    log.info("DART corp_codes to backfill: %d", len(rows))

    t0 = time.time()
    n_ok = 0; n_fail = 0; n_total_rows = 0
    last_log = t0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(worker, c, s, years): s for c, s in rows}
        for i, fut in enumerate(as_completed(futs), start=1):
            sc, n, err = fut.result()
            if err:
                n_fail += 1
            else:
                n_ok += 1
                n_total_rows += n
            if time.time() - last_log > 30:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                eta = (len(rows) - i) / rate if rate else 0
                log.info(
                    "[%d/%d] %s ok=%d fail=%d rows=%d "
                    "elapsed=%.0fs ETA=%.0fmin",
                    i, len(rows), sc, n_ok, n_fail, n_total_rows,
                    elapsed, eta / 60,
                )
                last_log = time.time()
    log.info(
        "DONE — ok=%d fail=%d rows=%d in %.0fs (%.1f hr)",
        n_ok, n_fail, n_total_rows, time.time() - t0,
        (time.time() - t0) / 3600,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
