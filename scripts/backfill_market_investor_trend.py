"""One-off: aggregate existing per-ticker investor_flow into market-wide
market_investor_trend rows.

`investor_flow` carries ~40 trading days of per-ticker 외인/기관/개인
순매수 (in KRW raw). market_investor_trend wants daily totals per
market (KRW 백만). One SQL pass with SUM + GROUP BY + INSERT ... ON
CONFLICT does the whole job — no Naver crawl needed.

Source units: investor_flow.*_net are KRW raw (shares × close). The
crawl path itself comments this as "approximation"; magnitude +
direction are correct, intraday-weighted mean is not modeled. Sum is
robust because the approximation error is per-ticker random.

Target units: market_investor_trend.*_net are KRW 백만 (matches the
Naver integration API the daily ingest uses going forward). Divide by
1,000,000 during the aggregation INSERT.

Usage:
    python scripts/backfill_market_investor_trend.py
    python scripts/backfill_market_investor_trend.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("backfill_market_investor_trend")


# We aggregate per (day, market) and convert KRW → 백만 in SQL.
# The market column in `tickers` is "KOSPI" / "KOSDAQ" (matches
# market_investor_trend.market by design).
AGGREGATE_SQL = """
WITH per_day AS (
    SELECT
        i.day,
        t.market,
        SUM(i.foreign_net)     / 1000000.0 AS foreign_million,
        SUM(i.institution_net) / 1000000.0 AS institution_million,
        SUM(i.individual_net)  / 1000000.0 AS individual_million
    FROM investor_flow i
    JOIN tickers t ON t.ticker = i.ticker
    WHERE t.market IN ('KOSPI', 'KOSDAQ')
    GROUP BY i.day, t.market
)
INSERT INTO market_investor_trend
    (market, day, individual_net, foreign_net, institution_net)
SELECT market, day,
       ROUND(individual_million)::numeric,
       ROUND(foreign_million)::numeric,
       ROUND(institution_million)::numeric
FROM per_day
ON CONFLICT (market, day) DO UPDATE SET
    individual_net  = EXCLUDED.individual_net,
    foreign_net     = EXCLUDED.foreign_net,
    institution_net = EXCLUDED.institution_net
"""

PREVIEW_SQL = """
SELECT i.day, t.market, COUNT(*) AS n_tickers,
       SUM(i.foreign_net)/1000000.0 AS f_million,
       SUM(i.institution_net)/1000000.0 AS i_million,
       SUM(i.individual_net)/1000000.0 AS p_million
FROM investor_flow i
JOIN tickers t ON t.ticker = i.ticker
WHERE t.market IN ('KOSPI','KOSDAQ')
GROUP BY i.day, t.market
ORDER BY i.day DESC, t.market
LIMIT 6
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be inserted; do not write.")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(PREVIEW_SQL)
            sample = cur.fetchall()
            log.info("Preview (top 6 most-recent rows that would be written):")
            for r in sample:
                log.info("  %s %s n=%d f=%s i=%s p=%s",
                         r[0], r[1], r[2], r[3], r[4], r[5])

    if args.dry_run:
        log.info("dry-run — no writes performed.")
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(AGGREGATE_SQL)
            n = cur.rowcount
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM market_investor_trend")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT MIN(day), MAX(day) FROM market_investor_trend"
            )
            mn, mx = cur.fetchone()
    log.info("upserted %d rows; table now has %d total (range %s → %s)",
             n, total, mn, mx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
