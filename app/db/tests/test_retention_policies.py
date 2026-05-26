"""Static-analysis tests for retention policies.

Two layers of safety:

  1. **Manual checklist** (`_REQUIRED_TABLES`): explicit table names we
     KNOW must have retention. Catches removals of existing rules.

  2. **Auto-discovery**: scan `migrations/*.sql` for `CREATE TABLE`
     statements and assert each user-data table has a policy (or is on
     the exempt list). Catches FORGETTING to add a rule when a new
     ingest table is introduced — the failure mode the user worried
     about ("새로 적재되는 테이블이 생기면 같이 룰 추가하고있고?").

If a future PR adds a new ingest target (e.g. earnings transcripts) and
forgets the matching retention rule, the auto-discovery layer fails.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.db import retention


# Tables that grow with cron ingest and must therefore have at least one
# DELETE rule somewhere in POLICIES. Stable across schema changes.
_REQUIRED_TABLES = {
    "bars",
    "investor_flow",
    "disclosures",
    "scan_results",
    "alerts",
    "fundamentals",     # added 2026-05-19 with SEC ingest
    "analyze_results",
    "feedback",         # added 2026-05-19 with /feedback page
    "short_sales",      # added 2026-05-19 with market signals (027)
    "market_warnings",  # ditto
    "dividend_info",    # ditto
    "earnings_calendar",        # added 2026-05-20 with investor intel (029)
    "analyst_consensus",        # ditto
    "institutional_ownership",  # ditto
    "disclosure_alert_seen",    # added 2026-05-20 with disclosure alerts (030)
    # search_history is self-trimming via DB trigger — exempt from rule below
}

# Tables that DON'T need a retention rule, with the reason:
#   - bounded by row count (1 row per ticker / user / etc.)
#   - has its own trimming mechanism (trigger, RPC, app-level)
#   - reference / config / one-time-write surface
# When the auto-discovery layer flags a NEW table missing from POLICIES,
# either add a rule to retention.POLICIES OR add the name here with a
# reason. Both are explicit decisions — neither happens by accident.
_RETENTION_EXEMPT = {
    "users",                  # bounded by signup count; has its own e2e GC
    "watchlist",              # bounded by user × ticker, user-owned
    "tickers",                # universe master; bounded by exchanges
    "alert_preferences",      # 1 row per user × signal_type
    "access_requests",        # 1 row per user (UPSERT)
    "telegram_link_tokens",   # short-lived; consumed once
    "telegram_bot_state",     # 1 row total
    "search_history",         # self-trimming AFTER INSERT trigger
    "company_profile",        # 1 row per ticker
    "macro_series",           # bounded by N indicators × years (cap inside)
    "macro_state",            # 1 row total
    "financials_eval",        # 1 row per ticker, overwritten
    "factors_eval",           # 1 row per ticker, overwritten
    "dividend_info",          # 1 row per ticker (covered by engagement filter)
    "push_subscriptions",     # 1 row per user × endpoint
    "health_ping",            # 1 row total — Supabase keepalive ping
    "watchlist_groups",       # 1 row per user × group (bounded), user-owned
    "themes",                 # ~265 rows (Naver theme universe), weekly upsert
    "theme_members",          # ~6K rows, fully replaced per theme on each cron
    "theme_metrics_cache",    # ~265 rows, TRUNCATE+INSERT every weekly cron
    "migrations_audit",       # append-only history, ~1 row per applied migration
    "us_bars",                # Phase 6 ad-hoc cache, self-evicts via us_ticker_cache (7d cascade in daily-data.yml)
    "us_ticker_cache",        # Phase 6 ad-hoc cache, 7d TTL via app.db.us_bars_cache.evict_stale (daily-data.yml step)
    "stop_loss_alert_seen",   # bounded per (user × ticker × week) — naturally small (active holdings only)
    "paper_trades",           # legacy table (replaced by paper_positions + paper_fills in migration 052) — kept until drop migration; bounded by user × ticker
    "paper_positions",        # broker-standard position store (migration 052) — bounded by user × ticker × open-era; win_rate/payoff stats need full closed history
    "paper_fills",            # append-only buy/sell log for paper_positions (migration 052); bounded by N positions × fills, retention via position lifecycle (cascade on delete)
}

# Tables created in migrations but later dropped — ignored by discovery.
_RETENTION_DROPPED = {
    "themes", "theme_daily", "theme_members",   # dropped 2026-05-19
    "chart_data",                                 # dropped migration 014
    "news",                                       # dropped migration 015
    "trade_log",                                  # dropped migration 024
    "bars_daily",                                 # dropped migration 025
}


def _all_tables_in_migrations() -> set[str]:
    """Walk migrations/*.sql, collect every CREATE TABLE IF NOT EXISTS
    target, minus the ones explicitly dropped later. Returns the
    current logical schema as a set of table names.
    """
    repo_root = Path(__file__).resolve().parents[3]
    mig_dir = repo_root / "migrations"
    if not mig_dir.exists():
        return set()
    create_re = re.compile(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)",
        re.IGNORECASE,
    )
    found: set[str] = set()
    for sql_path in sorted(mig_dir.glob("*.sql")):
        text = sql_path.read_text(encoding="utf-8")
        for m in create_re.finditer(text):
            found.add(m.group(1).lower())
    return found - _RETENTION_DROPPED

# Per-ticker tables that must additionally have an engagement-set filter
# (`WHERE ticker NOT IN (...watchlist...)`). Without this, US tickers
# auto-seeded by search would accumulate forever.
_NEEDS_ENGAGEMENT_FILTER = {
    "bars",
    "fundamentals",
    "disclosures",
    "scan_results",
    "analyze_results",
    "short_sales",
    "market_warnings",
    "dividend_info",
    "earnings_calendar",
    "analyst_consensus",
    "institutional_ownership",
}


def _tables_in_policies() -> set[str]:
    return {tbl for tbl, _, _ in retention.POLICIES}


def test_every_required_table_has_a_policy():
    present = _tables_in_policies()
    missing = _REQUIRED_TABLES - present
    assert not missing, (
        f"retention.POLICIES missing rules for: {sorted(missing)}. "
        "Cron-fed tables MUST have at least one retention rule, or the "
        "Supabase 500MB tier fills up silently."
    )


def test_engagement_filter_present_for_per_ticker_tables():
    """Verify the WHERE clause includes the engagement set filter
    (KR universe ∪ watchlist) for each per-ticker table.
    """
    for tbl in _NEEDS_ENGAGEMENT_FILTER:
        matching = [
            sql for (t, sql, _) in retention.POLICIES
            if t == tbl and isinstance(sql, str)
        ]
        assert matching, f"{tbl} has no string-based policy"
        # At least one of the rules for this table must mention the
        # watchlist engagement set. The literal SQL text is the
        # contract — if someone refactors the engagement set into a
        # function we should update this test to match.
        has_engagement = any(
            "watchlist" in sql and "last_accessed_at" in sql
            for sql in matching
        )
        assert has_engagement, (
            f"{tbl} retention rules don't reference the watchlist "
            f"engagement set. Without it, auto-seeded US tickers "
            f"accumulate forever."
        )


def test_policy_descriptions_present():
    """Descriptions show up in cron logs; missing ones make triage hard."""
    for tbl, _, desc in retention.POLICIES:
        assert desc, f"{tbl} policy has empty description"


def test_db_size_thresholds_present():
    """retention.main MUST measure DB size at the end and escalate
    once it crosses the Supabase 500MB hard cap. Regression guard:
    the 2026-05-20 incident saw the DB hit 497MB (99.4%) — without
    this monitoring step there's no warning before Supabase puts
    the DB in read-only mode mid-cron.
    """
    src = (Path(__file__).resolve().parents[1] / "retention.py").read_text(
        encoding="utf-8",
    )
    # Must reference both thresholds
    assert "0.85" in src or "SOFT_LIMIT" in src, "soft limit missing"
    assert "0.90" in src or "HARD_LIMIT" in src, "hard limit missing"
    # Must measure pg_database_size after retention runs
    assert "pg_database_size" in src
    # Must call VACUUM FULL bars on emergency (biggest table)
    assert "VACUUM FULL bars" in src
    # Must exit non-zero if still over hard limit
    assert "return 2" in src, "no non-zero exit when retention can't recover"


def test_no_new_table_silently_skips_retention():
    """Auto-discovery: every table CREATE'd by a migration must EITHER
    have a retention rule OR be on the exempt list with a documented
    reason. Catches the failure mode where someone adds a new ingest
    table (e.g. `earnings_calendar`) but forgets to wire retention —
    the table then grows forever and the Supabase 500 MB tier silently
    fills up.

    The fix when this fails: either add a rule to retention.POLICIES,
    or add the table name to `_RETENTION_EXEMPT` above with a one-line
    reason for why retention isn't needed.
    """
    discovered = _all_tables_in_migrations()
    covered = _tables_in_policies() | _RETENTION_EXEMPT
    unhandled = discovered - covered
    assert not unhandled, (
        f"Tables created by migrations but with no retention rule "
        f"AND not on the exempt list: {sorted(unhandled)}.\n"
        f"Either:\n"
        f"  1. add a rule to retention.POLICIES (see existing entries), or\n"
        f"  2. add the table to _RETENTION_EXEMPT with the reason "
        f"(self-trimming / bounded / etc.)\n"
        f"This test exists so adding an ingest table without retention "
        f"can't slip through review."
    )
