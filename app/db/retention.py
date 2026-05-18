"""DB retention enforcement — keep Supabase under the 500MB free tier.

Each cron-fed ingest module calls the matching `prune_*` function as its
last step. Idempotent — re-running on already-pruned data is a no-op.

Retention windows chosen so the site's display + analysis still has the
data it needs:

  bars_daily      2 years  (scan_daily reads `--years 2` for the analyzer)
  investor_flow   90 days  (site shows last 5; 90 buffers any drill-down)
  disclosures     1 year   (site lists last 30; 1y for compliance dashboards)
  scan_results    inactive ≥ 30 days  (active signals stay; cron toggles flags)
  theme_daily     180 days (6-month heatmap is the max user-facing window)

`macro_series`, `themes`, `tickers`, `analyze_results`, `financials_eval`,
`factors_eval`, `theme_members` are either bounded by universe size or
already overwritten in place; no retention needed.

Run standalone:
    python -m app.db.retention            # prune all
    python -m app.db.retention --dry-run  # show counts, no DELETE
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("retention")

# (table, sql, description) — order matters only for the dry-run printout.
POLICIES: list[Tuple[str, str, str]] = [
    (
        "bars_daily",
        "DELETE FROM bars_daily WHERE bar_date < CURRENT_DATE - INTERVAL '2 years'",
        "2 years",
    ),
    (
        "investor_flow",
        "DELETE FROM investor_flow WHERE day < CURRENT_DATE - INTERVAL '90 days'",
        "90 days",
    ),
    (
        "disclosures",
        "DELETE FROM disclosures WHERE filed_date < CURRENT_DATE - INTERVAL '1 year'",
        "1 year",
    ),
    (
        "scan_results",
        "DELETE FROM scan_results "
        "WHERE is_active = false "
        "AND detected_at < CURRENT_DATE - INTERVAL '30 days'",
        "inactive ≥ 30 days",
    ),
    (
        "theme_daily",
        "DELETE FROM theme_daily WHERE day < CURRENT_DATE - INTERVAL '180 days'",
        "180 days",
    ),
]


def prune_one(table: str, sql: str, dry_run: bool = False) -> int:
    """Run a single retention DELETE; return rows affected."""
    if dry_run:
        # Estimate by converting DELETE → SELECT COUNT(*).
        count_sql = sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1)
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql)
                return cur.fetchone()[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.rowcount


# Per-table convenience wrappers — each ingest module imports its own.

def prune_bars_daily() -> int:
    return prune_one(*POLICIES[0][:2])


def prune_investor_flow() -> int:
    return prune_one(*POLICIES[1][:2])


def prune_disclosures() -> int:
    return prune_one(*POLICIES[2][:2])


def prune_scan_results() -> int:
    return prune_one(*POLICIES[3][:2])


def prune_theme_daily() -> int:
    return prune_one(*POLICIES[4][:2])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )

    verb = "would delete" if args.dry_run else "deleted"
    total = 0
    for table, sql, desc in POLICIES:
        n = prune_one(table, sql, dry_run=args.dry_run)
        total += n
        log.info("%-15s (retain %s)  %s %d rows", table, desc, verb, n)
    log.info("total: %s %d rows", verb, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
