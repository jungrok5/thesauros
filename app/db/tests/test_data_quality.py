"""Data-quality tests for cron-fed Supabase tables.

These are guardrails — if cron stops feeding a table, or a third-party
API silently breaks (KIS vts 500s, FDR endpoint shifts, DART rate
limit), one of these assertions catches it before users notice.

Each test reads a single MAX-aggregate or COUNT — fast, no
side-effects, safe to run in CI on every PR. Critical-but-known-broken
tables are flagged with `@pytest.mark.xfail` and a reason so the suite
fails loudly when they start working again (i.e., when someone backfills
the data).

Run:
    python -m pytest app/db/tests/test_data_quality.py -v
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytest
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402


def _scalar(sql: str, *args: Any) -> Any:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args if args else None)
            row = cur.fetchone()
    return row[0] if row else None


def _today() -> date:
    return date.today()


# Number of calendar days we tolerate between MAX(date) and today before
# flagging a freshness regression. Picked generous enough to survive a
# weekend (3 days) plus one missed cron run (2 days) = 5.
TRADING_DAYS_GRACE = 5

# ─────────────────────────────────────────────────────────────────────
# FRESHNESS — last data point must be within N days of today
# ─────────────────────────────────────────────────────────────────────

def test_bars_weekly_freshness():
    """Weekly OHLCV. Cron-fed by ingest_bars (FDR resample W+M for KR,
    Naver weekCandle for US watchlist) every Friday 17:00 KST. Grace
    window is 8 days since weekly bars only land once a week."""
    latest = _scalar("SELECT MAX(bar_date) FROM bars WHERE granularity = 'W'")
    assert latest is not None, "bars (granularity=W) is empty"
    age = (_today() - latest).days
    assert age <= 8, (
        f"bars weekly stale: latest={latest} ({age}d old) — ingest_bars cron not running?"
    )


def test_scan_results_freshness():
    latest = _scalar(
        "SELECT MAX(detected_at)::date FROM scan_results WHERE is_active=true"
    )
    assert latest is not None, "scan_results has no active rows"
    age = (_today() - latest).days
    assert age <= TRADING_DAYS_GRACE, (
        f"scan_results stale: latest={latest} ({age}d) — scan_daily cron not running?"
    )


def test_analyze_results_freshness():
    latest = _scalar("SELECT MAX(as_of) FROM analyze_results")
    assert latest is not None, "analyze_results is empty"
    age = (_today() - latest).days
    assert age <= TRADING_DAYS_GRACE, (
        f"analyze_results stale: latest={latest} ({age}d) — scan_daily not running?"
    )


def test_macro_state_freshness():
    latest = _scalar("SELECT updated_at::date FROM macro_state WHERE id=1")
    assert latest is not None, "macro_state row missing"
    age = (_today() - latest).days
    # macro_state changes daily.
    assert age <= 3, (
        f"macro_state stale: {latest} — publish_macro cron not running?"
    )


def test_macro_series_freshness():
    """FRED series — most update monthly (CPI/PPI/M2), some monthly-Q.
    14d grace accommodates the slowest series."""
    latest = _scalar("SELECT MAX(date) FROM macro_series")
    assert latest is not None
    age = (_today() - latest).days
    assert age <= 14, f"macro_series stale: {latest} ({age}d)"


def test_investor_flow_freshness():
    latest = _scalar("SELECT MAX(day) FROM investor_flow")
    assert latest is not None
    age = (_today() - latest).days
    assert age <= TRADING_DAYS_GRACE, (
        f"investor_flow stale: {latest} ({age}d) — ingest cron not running?"
    )


def test_financials_eval_freshness():
    """Weekly cadence — 14d grace covers one missed weekly-fundamentals run."""
    latest = _scalar("SELECT MAX(updated_at)::date FROM financials_eval")
    assert latest is not None
    age = (_today() - latest).days
    assert age <= 14, (
        f"financials_eval stale: {latest} ({age}d) — weekly-fundamentals not running?"
    )


def test_tickers_freshness():
    """Weekly refresh on Sundays."""
    latest = _scalar("SELECT MAX(updated_at)::date FROM tickers WHERE is_active=true")
    assert latest is not None
    age = (_today() - latest).days
    assert age <= 14, (
        f"tickers stale: {latest} ({age}d) — weekly-tickers-refresh not running?"
    )


# ─────────────────────────────────────────────────────────────────────
# COVERAGE — minimum unique-ticker counts
# ─────────────────────────────────────────────────────────────────────

def test_tickers_universe_size():
    n = _scalar("SELECT COUNT(*) FROM tickers WHERE is_active = true")
    # KR-only universe post-2026-05-22 (migration 045): KOSPI ~900 +
    # KOSDAQ ~1,800 ≈ 2,700. Cushion floor at 2,500 so a temporary
    # weekly-tickers-refresh hiccup still fails loudly, not silently.
    assert n >= 2_500, (
        f"tickers active universe = {n}, expected ≥ 2,500 (KOSPI + KOSDAQ)"
    )


def test_bars_weekly_ticker_coverage():
    """Weekly bars should cover the KR universe (≈2,700) on the most
    recent *settled* week (defined as the most recent week-ending date
    that has at least 1,000 tickers covered)."""
    n = _scalar(
        """
        SELECT COUNT(DISTINCT ticker) FROM bars
        WHERE granularity = 'W'
          AND bar_date = (
            SELECT bar_date FROM bars
            WHERE granularity = 'W'
            GROUP BY bar_date HAVING COUNT(*) >= 1000
            ORDER BY bar_date DESC LIMIT 1
        )
        """
    )
    assert n is not None and n >= 2000, (
        f"bars weekly most-recent-settled-week coverage = {n} tickers, "
        "expected ≥ 2000 — ingest_bars not running across full universe?"
    )


def test_investor_flow_ticker_coverage():
    """Naver Finance frgn page covers full KOSPI/KOSDAQ universe. If we
    fall below 2000 distinct tickers, the new scraper is regressing."""
    n = _scalar("SELECT COUNT(DISTINCT ticker) FROM investor_flow")
    assert n >= 2000, (
        f"investor_flow coverage = {n} tickers, expected ≥ 2000 "
        "(Naver scraper regression?)"
    )


def test_financials_eval_ticker_coverage():
    n = _scalar("SELECT COUNT(DISTINCT ticker) FROM financials_eval")
    assert n >= 2000, (
        f"financials_eval coverage = {n}, expected ≥ 2000 KR tickers"
    )


# ─────────────────────────────────────────────────────────────────────
# COMPLETENESS — null-rate / value sanity
# ─────────────────────────────────────────────────────────────────────

def test_investor_flow_values_non_empty():
    """Ensure foreign_shares_net is actually populated for the latest day
    (regression guard against the previous KIS-vts bug where all fields
    came back as empty strings)."""
    latest_day = _scalar("SELECT MAX(day) FROM investor_flow")
    assert latest_day is not None
    nonnull = _scalar(
        "SELECT COUNT(*) FROM investor_flow "
        "WHERE day = %s AND foreign_shares_net IS NOT NULL",
        latest_day,
    )
    total = _scalar(
        "SELECT COUNT(*) FROM investor_flow WHERE day = %s", latest_day,
    )
    assert total > 0
    ratio = nonnull / total
    assert ratio >= 0.8, (
        f"investor_flow.foreign_shares_net is NULL for {(1-ratio)*100:.0f}% "
        f"of latest day rows — values are not being parsed correctly."
    )


def test_bars_recent_prices_positive():
    """Sanity: no negative/zero closing prices on recent bars (any granularity)."""
    bad = _scalar(
        "SELECT COUNT(*) FROM bars "
        "WHERE bar_date >= CURRENT_DATE - INTERVAL '60 days' AND close <= 0"
    )
    assert bad == 0, f"{bad} bars rows have non-positive close in last 60 days"


# ─────────────────────────────────────────────────────────────────────
# BUDGET — keep DB under Supabase Free 500MB
# ─────────────────────────────────────────────────────────────────────

def test_db_size_under_free_tier():
    """Retention policies (app/db/retention.py) should keep the DB
    indefinitely under 500MB. If this trips, something is bypassing
    retention or a new table is growing unchecked."""
    bytes_size = _scalar("SELECT pg_database_size(current_database())")
    mb = bytes_size / (1024 * 1024)
    assert mb < 500, (
        f"DB size = {mb:.1f} MB ≥ 500 MB Free-tier ceiling. "
        "Either retention stopped running, or a new table is unbounded. "
        "Run `python -m app.db.retention --dry-run` to inspect."
    )


def test_disclosures_populated():
    """DART OpenAPI 공시 ingest. Needs DART_API_KEY in cron env."""
    n = _scalar("SELECT COUNT(DISTINCT ticker) FROM disclosures")
    assert n >= 500, (
        f"disclosures coverage = {n} tickers, expected ≥ 500 — "
        "is ingest_news (DART) wired into daily-scan?"
    )
