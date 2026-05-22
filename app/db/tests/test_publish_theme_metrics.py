"""Tests for the publish_theme_metrics safety net (회고 #14).

theme_metrics() RPC takes 9-10s cold. If it returns 0 rows (e.g.,
022_drop_themes replay wiping theme_members), naive TRUNCATE-then-
INSERT would empty the cache and force every /themes page-load through
the slow RPC fallback — site-wide degradation.

The fix: probe the RPC into a temp table first; if it has fewer than
_MIN_THEMES rows, raise PublishAborted and leave the existing (stale)
cache intact. Stale data > 9-10s pages.

These tests pin that safety net so a future "speedup" refactor can't
accidentally remove it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import publish_theme_metrics
from app.db.publish_theme_metrics import PublishAborted, publish


def _stub_conn(rpc_count: int, prev_cache_count: int = 200):
    """Build a context-manager get_conn whose cursor returns the
    counts we want when publish() queries them."""
    cur = MagicMock()
    fetchone_returns = iter([(rpc_count,), (prev_cache_count,)])
    cur.fetchone.side_effect = lambda: next(fetchone_returns)
    cur.rowcount = rpc_count
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_publish_writes_when_rpc_returns_healthy_count():
    """Happy path — RPC returns ≥ _MIN_THEMES rows, cache gets swapped."""
    conn, cur = _stub_conn(rpc_count=265, prev_cache_count=200)
    with patch.object(publish_theme_metrics, "get_conn", return_value=conn):
        n = publish()
    assert n == 265
    # The atomic swap must have happened: CREATE TEMP, two COUNTs,
    # TRUNCATE, INSERT.
    sqls = [call.args[0] if call.args else "" for call in cur.execute.call_args_list]
    assert any("CREATE TEMP TABLE _tm_new" in s for s in sqls)
    assert any("TRUNCATE TABLE theme_metrics_cache" in s for s in sqls)
    assert any("INSERT INTO theme_metrics_cache" in s for s in sqls)


def test_publish_aborts_when_rpc_returns_zero_rows():
    """Disaster scenario — RPC returns 0 (theme_members got wiped).
    Must raise PublishAborted, must NOT call TRUNCATE."""
    conn, cur = _stub_conn(rpc_count=0, prev_cache_count=265)
    with patch.object(publish_theme_metrics, "get_conn", return_value=conn):
        with pytest.raises(PublishAborted) as excinfo:
            publish()
    assert "0 rows" in str(excinfo.value)
    assert "265 rows" in str(excinfo.value)   # mentions kept cache count

    sqls = [call.args[0] if call.args else "" for call in cur.execute.call_args_list]
    # TRUNCATE and INSERT must NOT appear — that's the whole point.
    assert not any("TRUNCATE TABLE theme_metrics_cache" in s for s in sqls), (
        "PublishAborted path must skip TRUNCATE to preserve stale cache"
    )


def test_publish_aborts_below_min_threshold():
    """Below _MIN_THEMES (50) but non-zero — still abort. Edge case to
    catch partial-ingest scenarios."""
    conn, cur = _stub_conn(rpc_count=42, prev_cache_count=265)
    with patch.object(publish_theme_metrics, "get_conn", return_value=conn):
        with pytest.raises(PublishAborted):
            publish()
    sqls = [call.args[0] if call.args else "" for call in cur.execute.call_args_list]
    assert not any("TRUNCATE TABLE theme_metrics_cache" in s for s in sqls)


def test_main_exits_nonzero_on_abort():
    """CLI entrypoint must exit non-zero on abort so the GH Actions
    step shows as failed (continue-on-error still lets cron proceed,
    but the failure surfaces in the admin end-ping)."""
    with patch.object(publish_theme_metrics, "publish",
                      side_effect=PublishAborted("test")):
        rc = publish_theme_metrics.main()
    assert rc == 2


def test_main_exits_zero_on_success():
    with patch.object(publish_theme_metrics, "publish", return_value=265):
        rc = publish_theme_metrics.main()
    assert rc == 0
