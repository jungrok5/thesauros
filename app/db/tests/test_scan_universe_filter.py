"""Regression test for the scan_daily universe-filter optimization.

Background: 2026-05-22 cron took 1h2m vs the usual 25m. Root cause —
scan_daily iterated all 6,913 US tickers with no bars in DB (Naver
cloud-IP blocked, only watchlist US fetched). Each empty ticker cost
~0.2s DB lookup before falling into `skipped_no_history` = ~23 min
wasted. Fix: filter the universe at the SQL level via EXISTS so
ticker without bars don't enter the per-ticker loop.

These tests pin the contract that:
  1. The default universe path filters out ticker with no weekly bars.
  2. The explicit `--tickers` path bypasses the filter (one-off mode
     used by analyze-ticker.yml dispatch — caller knows the ticker
     might not have bars yet).
  3. The bars filter restricts to granularity='W' (the analyzer's
     primary timeframe; daily bars storage was removed in 2026-05-18
     migration but the constant guards future schema drift).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import scan_daily


def _stub_conn(executed: list):
    """Return a context-manager `get_conn` that records every SQL the
    code executes, so the test can assert against the actual query."""
    cur = MagicMock()
    cur.fetchall.return_value = []   # default; tests can override
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    def _execute(sql, params=None):
        executed.append((sql, params or []))
    cur.execute = _execute

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


# ─────────────────────────────────────────────────────────────────────
# Default path — bars EXISTS filter applied
# ─────────────────────────────────────────────────────────────────────

def test_default_query_includes_bars_exists_filter():
    """No explicit ticker list → universe is filtered to tickers that
    have at least one weekly bar in DB."""
    executed: list = []
    conn, cur = _stub_conn(executed)
    cur.fetchall.return_value = [("005930.KS", "KOSPI")]
    with patch.object(scan_daily, "get_conn", return_value=conn):
        result = scan_daily._list_tickers(markets=["KOSPI"])

    assert result == ["005930.KS"]
    assert len(executed) == 1
    sql, _params = executed[0]
    assert "EXISTS" in sql
    assert "bars.ticker = tickers.ticker" in sql
    assert "bars.granularity = 'W'" in sql


def test_market_filter_combined_with_bars_filter():
    """Both filters live in one WHERE clause joined by AND — the EXISTS
    subquery does NOT replace the market filter."""
    executed: list = []
    conn, _ = _stub_conn(executed)
    with patch.object(scan_daily, "get_conn", return_value=conn):
        scan_daily._list_tickers(markets=["KOSPI", "KOSDAQ"])

    sql, params = executed[0]
    assert "market = ANY" in sql
    assert "EXISTS" in sql
    assert sql.count("AND") >= 2   # is_active AND market AND EXISTS
    assert params == [["KOSPI", "KOSDAQ"]]


def test_default_no_market_filter_still_applies_bars_filter():
    """Bare `_list_tickers()` (no markets, no explicit tickers) must
    still apply the bars EXISTS filter — that's the cron's default
    invocation path."""
    executed: list = []
    conn, _ = _stub_conn(executed)
    with patch.object(scan_daily, "get_conn", return_value=conn):
        scan_daily._list_tickers()

    sql, _ = executed[0]
    assert "EXISTS" in sql


# ─────────────────────────────────────────────────────────────────────
# Explicit ticker list — bypass filter
# ─────────────────────────────────────────────────────────────────────

def test_explicit_ticker_list_bypasses_bars_filter():
    """`--tickers AAPL` (one-off from analyze-ticker.yml dispatch) must
    NOT apply the bars filter. The caller is explicitly asking for that
    ticker; if it has no bars yet, scan_daily logs `insufficient_history`
    rather than silently dropping it from the universe."""
    executed: list = []
    conn, _ = _stub_conn(executed)
    with patch.object(scan_daily, "get_conn", return_value=conn):
        scan_daily._list_tickers(tickers=["AAPL"])

    sql, params = executed[0]
    assert "EXISTS" not in sql, (
        "explicit --tickers path must skip the bars filter; got: " + sql
    )
    assert "ticker = ANY" in sql
    assert params == [["AAPL"]]


# ─────────────────────────────────────────────────────────────────────
# Active-only invariant — defense in depth
# ─────────────────────────────────────────────────────────────────────

def test_query_always_filters_is_active():
    """Regression: every path must include is_active=true. Inactive
    tickers were delisted or renamed; scanning them produces noise."""
    executed: list = []
    conn, _ = _stub_conn(executed)
    with patch.object(scan_daily, "get_conn", return_value=conn):
        scan_daily._list_tickers(markets=["KOSPI"])

    sql, _ = executed[0]
    assert "is_active = true" in sql
