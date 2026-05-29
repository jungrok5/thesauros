"""Backfill `tickers.industry` from data/kr_sectors.csv (FDR snapshot).

Source: data/kr_sectors.csv built by `scripts/grid_phase5_factors.py`'s
universe-prep helpers (FDR StockListing('KOSPI-DESC' + 'KOSDAQ-DESC')).
161 distinct industry categories cover ~2,605 of the ~2,700 active KR
tickers.

Usage:
    python -m app.db.backfill_tickers_industry             # apply
    python -m app.db.backfill_tickers_industry --dry-run   # preview
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("backfill_tickers_industry")


def _load_csv() -> List[Tuple[str, str]]:
    csv_path = _ROOT / "data" / "kr_sectors.csv"
    pairs: List[Tuple[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            ind = (row.get("industry") or "").strip()
            tic = (row.get("ticker") or "").strip()
            if tic and ind:
                pairs.append((tic, ind))
    return pairs


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )

    pairs = _load_csv()
    if not pairs:
        log.error("no rows in data/kr_sectors.csv")
        return 1

    log.info("loaded %d (ticker, industry) pairs from csv", len(pairs))

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), COUNT(industry) FROM tickers "
                "WHERE market IN ('KOSPI','KOSDAQ')"
            )
            total_before, with_ind_before = cur.fetchone()
            log.info("KR tickers in DB: %d / with industry: %d",
                     total_before, with_ind_before)

    if args.dry_run:
        sample = pairs[:5]
        log.info("dry-run — sample %s", sample)
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE tickers SET industry = %s WHERE ticker = %s",
                [(ind, tic) for tic, ind in pairs],
            )
            cur.execute(
                "SELECT COUNT(industry), COUNT(DISTINCT industry) "
                "FROM tickers WHERE market IN ('KOSPI','KOSDAQ')"
            )
            with_ind_after, distinct_ind = cur.fetchone()
    log.info("after: KR tickers with industry: %d, distinct industries: %d",
             with_ind_after, distinct_ind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
