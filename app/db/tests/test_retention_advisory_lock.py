"""Tests for the retention advisory-lock guard (회고 #19/#56).

Friday 17 KST 에 daily-data + weekly-scan 두 cron 이 동시 발사되면
retention.py 도 둘 다에서 호출 → DELETE 동시 + dead tuple 폭증 가능.
Postgres advisory lock 으로 한쪽만 진행, 다른 한쪽은 graceful skip.

Also pin the schedule spacing in vercel.json — daily 0800 / weekly 0830
UTC = 17:00 / 17:30 KST. Direct overlap probability further reduced.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.db import retention


def _conn_returning(value: bool):
    cur = MagicMock()
    cur.fetchone.return_value = (value,)
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def test_try_advisory_lock_returns_true_when_acquired():
    with patch.object(retention, "get_conn", return_value=_conn_returning(True)):
        assert retention._try_advisory_lock() is True


def test_try_advisory_lock_returns_false_when_blocked():
    with patch.object(retention, "get_conn", return_value=_conn_returning(False)):
        assert retention._try_advisory_lock() is False


def test_main_skips_when_lock_unavailable():
    """다른 cron 이 retention 돌리는 중이면 두 번째는 graceful exit
    (return 0). DELETE 충돌 / dead tuple 폭증 회피."""
    with patch.object(retention, "_try_advisory_lock", return_value=False):
        # If lock unavailable, prune_one must NEVER be called.
        with patch.object(retention, "prune_one") as mock_prune:
            rc = retention.main([])
    assert rc == 0
    assert mock_prune.call_count == 0


def test_main_with_no_lock_flag_bypasses():
    """--no-lock CLI flag for emergency manual runs."""
    with patch.object(retention, "_try_advisory_lock") as mock_lock:
        with patch.object(retention, "prune_one", return_value=0):
            with patch.object(retention, "get_conn") as mock_conn:
                # main() uses get_conn for VACUUM + DB-size check too,
                # so wire up minimal stubs.
                cur = MagicMock()
                cur.fetchone.return_value = (100 * 1024 * 1024,)  # 100MB
                cur.__enter__ = MagicMock(return_value=cur)
                cur.__exit__ = MagicMock(return_value=False)
                conn = MagicMock()
                conn.cursor.return_value = cur
                conn.__enter__ = MagicMock(return_value=conn)
                conn.__exit__ = MagicMock(return_value=False)
                mock_conn.return_value = conn
                retention.main(["--no-lock"])
    # When --no-lock, _try_advisory_lock should NOT have been called.
    assert mock_lock.call_count == 0


# ─────────────────────────────────────────────────────────────────────
# Static check: vercel.json schedules don't overlap exactly
# ─────────────────────────────────────────────────────────────────────

def test_vercel_cron_schedules_dont_collide_exactly():
    """daily-data + weekly-scan 의 schedule 이 정확히 같은 분에 잡혀
    있으면 fail. 5분 이상 간격이어야 retention DELETE race 가능성 낮음."""
    # vercel.json moved to repo root in Phase 6 deploy fix (2026-05-24);
    # was previously inside web-next/. Fall back to legacy path for
    # branches that haven't picked up the move yet.
    repo_root = Path(retention.__file__).resolve().parents[2]
    candidates = [repo_root / "vercel.json",
                  repo_root / "web-next" / "vercel.json"]
    path = next((p for p in candidates if p.exists()), candidates[0])
    vercel = json.loads(path.read_text(encoding="utf-8"))
    crons = {c["path"]: c["schedule"] for c in vercel.get("crons", [])}
    daily = crons.get("/api/cron/daily-data")
    weekly = crons.get("/api/cron/weekly-scan")
    assert daily and weekly, "both daily-data and weekly-scan cron required"
    # Parse "min hour ..." — pull first two fields.
    def first_two(expr: str) -> tuple[str, str]:
        parts = expr.split()
        return parts[0], parts[1]
    daily_m, daily_h = first_two(daily)
    weekly_m, weekly_h = first_two(weekly)
    same_minute = daily_m == weekly_m and daily_h == weekly_h
    assert not same_minute, (
        f"daily ({daily}) and weekly ({weekly}) fire in the same minute — "
        "race condition risk. shift one by 5+ minutes."
    )
