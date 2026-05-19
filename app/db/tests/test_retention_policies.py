"""Static-analysis tests for retention policies.

We don't actually execute the DELETEs against the live DB — that would
churn real data and depend on a network. Instead we lock the policy
catalog itself: every table that grows from cron-fed ingest must have at
least one rule in `POLICIES`, and the engagement-set filter wording must
appear in the rules for tables that store per-ticker data.

If a future PR adds a new ingest target (e.g. earnings transcripts) and
forgets the matching retention rule, this test fails.
"""
from __future__ import annotations

from app.db import retention


# Tables that grow with cron ingest and must therefore have at least one
# DELETE rule somewhere in POLICIES. Stable across schema changes.
_REQUIRED_TABLES = {
    "bars",
    "investor_flow",
    "disclosures",
    "scan_results",
    "alerts",
    "fundamentals",   # added 2026-05-19 with SEC ingest
    "analyze_results",
    "feedback",       # added 2026-05-19 with /feedback page
    # search_history is self-trimming via DB trigger — exempt from rule below
}

# Per-ticker tables that must additionally have an engagement-set filter
# (`WHERE ticker NOT IN (...watchlist...)`). Without this, US tickers
# auto-seeded by search would accumulate forever.
_NEEDS_ENGAGEMENT_FILTER = {
    "bars",
    "fundamentals",
    "disclosures",
    "scan_results",
    "analyze_results",
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
