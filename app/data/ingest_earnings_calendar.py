"""Generate earnings_calendar rows from KR filing-cadence conventions
+ DART historical actuals.

Two layers feed the table:

  1. **Forward cadence** — KR-listed corps with Dec-end fiscal year
     are legally bound to file periodic reports by:
       1Q → May 15, 2Q → Aug 14, 3Q → Nov 14, FY → Mar 31 (next year).
     For each engaged ticker we INSERT the next 4 upcoming cutoffs.
     Cells populated: ticker, expected_date, report_type, source.
     EPS/revenue stay NULL until actuals come in.

  2. **Past actuals** — DART `fnlttSinglAcnt.json` already populates
     `fundamentals`. We don't re-fetch here; instead the API layer
     LEFT JOIN's analyst_consensus + fundamentals when serving the
     calendar page, so the user sees consensus vs actual side by side.

The "skip non-Dec-end" simplification is fine for KR — virtually all
KOSPI/KOSDAQ corps run a Dec fiscal year. The handful with off-cycle
years just won't get auto-populated; they're rare enough that the
explicit MISS is better than half-correct guesses.

usage:
    python -m app.data.ingest_earnings_calendar
    python -m app.data.ingest_earnings_calendar --tickers 005930.KS
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.data.ingest_market_signals import _engagement_kr_tickers  # noqa: E402
from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_earnings_calendar")

# KR periodic report legal cutoff dates (Dec fiscal year). The tuple
# is (report_type, month, day). 'FY' is filed in the NEXT calendar
# year by Mar 31.
_CADENCE: list[tuple[str, int, int, int]] = [
    # (label, year_offset, month, day)
    ("Q1", 0, 5, 15),
    ("Q2", 0, 8, 14),
    ("Q3", 0, 11, 14),
    ("FY", 1, 3, 31),
]


def _next_expected_dates(today: date) -> List[Tuple[date, str]]:
    """Return the next 4 upcoming (expected_date, report_type) pairs.
    We always look at this year's full cadence + next year's. Any
    cutoff in the future relative to `today` is kept; we then take
    the earliest 4.
    """
    candidates: list[tuple[date, str]] = []
    for year_seed in (today.year, today.year + 1):
        for label, off, m, d in _CADENCE:
            try:
                exp = date(year_seed + off, m, d)
            except ValueError:
                continue
            if exp >= today:
                candidates.append((exp, label))
    candidates.sort()
    return candidates[:4]


def _seed_one(ticker: str, today: date) -> int:
    upcoming = _next_expected_dates(today)
    if not upcoming:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for exp, rtype in upcoming:
                cur.execute(
                    """
                    INSERT INTO earnings_calendar
                      (ticker, expected_date, report_type, source)
                    VALUES (%s, %s, %s, 'dart_cadence')
                    ON CONFLICT (ticker, expected_date, report_type) DO NOTHING
                    """,
                    (ticker, exp, rtype),
                )
    return len(upcoming)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = args.tickers or _engagement_kr_tickers()
    if args.limit:
        tickers = tickers[: args.limit]
    log.info("earnings calendar seed — %d tickers", len(tickers))

    today = date.today()
    total = 0
    for t in tickers:
        try:
            total += _seed_one(t, today)
        except Exception as e:
            log.warning("ticker=%s error: %s", t, e)

    log.info("done — %d rows seeded", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
