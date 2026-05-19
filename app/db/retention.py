"""DB retention enforcement — keep Supabase under the 500MB free tier.

Each cron-fed ingest module calls the matching `prune_*` function as its
last step. Idempotent — re-running on already-pruned data is a no-op.

All timestamps in the DB are stored as UTC (Postgres `TIMESTAMPTZ`).
The `CURRENT_DATE - INTERVAL 'N days'` boundaries below evaluate in the
session's timezone — make sure the GitHub Actions runner is UTC (default
on `ubuntu-latest`).

Retention windows chosen so the site's display + analysis still has the
data it needs:

  bars (W)        5 years  (≈260 weekly rows per ticker; book MAs go up to 240)
  bars (M)        5 years  (≈60 monthly rows per ticker)
  investor_flow   14 days  (site shows last 5; 14 buffers any drill-down)
  disclosures     1 year + engagement set
  fundamentals    engagement set only (5 years rolling per ticker)
  scan_results    inactive ≥ 30 days  (active signals stay; cron toggles flags)

`macro_series`, `tickers`, `analyze_results`, `financials_eval`,
`factors_eval` are either bounded by universe size or already
overwritten in place; no retention needed.

**Engagement set** = KR universe (KOSPI + KOSDAQ active) ∪ watchlisted
tickers (category='holding' OR last_accessed_at within 90 days). Anything
outside is "data we no longer need" — applies symmetrically to bars,
fundamentals, disclosures, scan_results, analyze_results. The watchlist
row itself is never touched; if the user re-visits, the next cron
re-ingests.

Note (2026-05-19): theme_daily / themes / theme_members were dropped
along with the /themes page in the search-only pivot.

Run standalone:
    python -m app.db.retention            # prune all
    python -m app.db.retention --dry-run  # show counts, no DELETE
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Tuple, Union

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("retention")


def _prune_e2e_users(dry_run: bool) -> int:
    """Clean up @e2e.test artifacts older than 1 day. Needs two SQL
    statements because access_requests.decided_by is ON DELETE RESTRICT
    so we NULL it for any test-admin decisions before the user delete.
    """
    select_stale = (
        "SELECT id FROM users "
        "WHERE email ILIKE '%@e2e.test' "
        "AND created_at < CURRENT_DATE - INTERVAL '1 day'"
    )
    if dry_run:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM ({select_stale}) s")
                return cur.fetchone()[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE access_requests SET decided_by = NULL "
                f"WHERE decided_by IN ({select_stale})"
            )
            cur.execute(
                "DELETE FROM users WHERE email ILIKE '%@e2e.test' "
                "AND created_at < CURRENT_DATE - INTERVAL '1 day'"
            )
            return cur.rowcount


# (table, sql_or_callable, description). String → single-statement DELETE
# with auto dry-run conversion. Callable → custom (e.g. multi-statement
# users cleanup with FK NULL-out first).
Policy = Tuple[str, Union[str, Callable[[bool], int]], str]

POLICIES: list[Policy] = [
    (
        "bars",
        "DELETE FROM bars WHERE bar_date < CURRENT_DATE - INTERVAL '5 years'",
        "5 years (W + M)",
    ),
    (
        "investor_flow",
        "DELETE FROM investor_flow WHERE day < CURRENT_DATE - INTERVAL '14 days'",
        "14 days",
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
    # theme_daily retention removed 2026-05-19 — tables dropped along
    # with /themes page in the search-only pivot.
    # Alerts pile up at ~1-3 rows per user per signal-bearing ticker per
    # day. 90 days of history is plenty for "did I get notified about
    # this?" — older rows are dead weight.
    (
        "alerts",
        "DELETE FROM alerts WHERE created_at < CURRENT_DATE - INTERVAL '90 days'",
        "90 days",
    ),
    # ──────────────────────────────────────────────────────────────────
    # Generated-data TTL via engagement. The `active set` is the union
    # of the default scan universe (KOSPI/KOSDAQ — always kept) and any
    # ticker that has a FRESH watchlist entry (last_accessed_at within
    # 90 days; `holding` category never goes stale because the user has
    # money in it). Anything outside that set has its generated data
    # purged. The watchlist row itself is NEVER touched — the user
    # owns it. If they view the ticker again, last_accessed_at refreshes
    # and the next cron regenerates the data via Naver / FDR / SEC.
    # ──────────────────────────────────────────────────────────────────
    (
        "bars",
        """
        DELETE FROM bars WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside KR universe ∪ engaged watchlist",
    ),
    (
        "scan_results",
        """
        DELETE FROM scan_results WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "same engagement set",
    ),
    (
        "analyze_results",
        """
        DELETE FROM analyze_results WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "same engagement set",
    ),
    # `fundamentals` is per-(ticker, concept, fy). DART writes KR (already
    # covered by the KOSPI/KOSDAQ universe arm); SEC writes US which can
    # be unbounded if every searched US ticker keeps accumulating. Same
    # engagement filter as bars — non-KR ticker must be watchlisted (or
    # recently accessed) to keep its fundamentals.
    (
        "fundamentals",
        """
        DELETE FROM fundamentals WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # `disclosures` already has the 1-year date filter above; this adds
    # the engagement filter so a US ticker that was searched once a year
    # ago doesn't keep its 30 SEC filings forever just because the
    # date-based rule treats them as "fresh".
    (
        "disclosures",
        """
        DELETE FROM disclosures WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # Feedback tickets: keep open + in-progress forever; closed ones
    # (resolved or wont-fix) are dead weight after 90 days. updated_at
    # is bumped by the touch_feedback_updated_at trigger on status
    # changes, so this counts from when the ticket actually closed.
    (
        "feedback",
        """
        DELETE FROM feedback
         WHERE status IN ('resolved', 'wont_fix')
           AND updated_at < CURRENT_DATE - INTERVAL '90 days'
        """,
        "closed ≥ 90 days",
    ),
    # search_history is self-trimming via the trg_trim_search_history
    # trigger (30 newest per user). No retention rule needed.
    # investor_flow is KR-only by construction (Naver frgn page), so
    # the date-based 90d rule above already handles it.
    # E2E test artifacts — Playwright sessions upsert @e2e.test users
    # via /api/e2e-test/issue-session. The session-mint endpoint does
    # its own rolling 1h GC; this is the daily safety net for any
    # stragglers. access_requests.decided_by is ON DELETE RESTRICT so
    # the callable above NULLs test-admin decisions first, then deletes.
    ("users", _prune_e2e_users, "e2e test users 24h"),
]


def prune_one(
    table: str,
    sql_or_fn: Union[str, Callable[[bool], int]],
    dry_run: bool = False,
) -> int:
    """Run a single retention rule; return rows affected. Strings are
    auto-converted DELETE→COUNT for dry runs; callables get a dry_run flag."""
    if callable(sql_or_fn):
        return sql_or_fn(dry_run)
    sql = sql_or_fn
    if dry_run:
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

def prune_bars() -> int:
    return prune_one(*POLICIES[0][:2])


def prune_investor_flow() -> int:
    return prune_one(*POLICIES[1][:2])


def prune_disclosures() -> int:
    return prune_one(*POLICIES[2][:2])


def prune_scan_results() -> int:
    return prune_one(*POLICIES[3][:2])


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
