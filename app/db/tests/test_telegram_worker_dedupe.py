"""Regression tests for telegram_worker alert dedupe.

The 2026-05-20 SDI bug: the same alert fired 13 times in 24h
because `_already_alerted` used `alerts.created_at >= signal_detected_at`,
and `signal_detected_at` was in the future (weekly bar's next-Friday
close), so the comparison was always false. The fix switches to a
time-window dedupe (`created_at >= NOW() - INTERVAL '24h'`) which
doesn't depend on signal_detected_at at all.

This test exercises the live `_already_alerted` against a fresh
ALERTS row to lock in the new behavior. DB-backed (uses the existing
test conn pool); marked as the only DB-aware test in this file.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402
from app.db.telegram_worker import _already_alerted  # noqa: E402


def _has_db() -> bool:
    return bool(os.environ.get("SUPABASE_DB_PASSWORD"))


@pytest.fixture
def test_user_and_ticker():
    """Create a transient @e2e.test user + a known ticker for the test.
    Cleaned up at teardown. Tickers reused (no insert).
    """
    if not _has_db():
        pytest.skip("DB not configured")
    email = f"dedupe-{uuid.uuid4().hex[:8]}@e2e.test"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                (email, "dedupe test"),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO alert_preferences (user_id) VALUES (%s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (uid,),
            )
            # Use Samsung (real ticker; doesn't matter for dedupe)
            cur.execute(
                "INSERT INTO tickers (ticker, name, market, is_active) "
                "VALUES ('TEST.TST', 'dedupe-test', 'TEST', true) "
                "ON CONFLICT (ticker) DO NOTHING"
            )
    yield str(uid), "TEST.TST"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE user_id = %s", (uid,))
            cur.execute("UPDATE access_requests SET decided_by = NULL "
                        "WHERE decided_by = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))


def test_dedupe_blocks_repeat_within_24h(test_user_and_ticker):
    """Insert an alert NOW; verify _already_alerted returns True for the
    same (user, ticker, alert_type) — the canonical happy path."""
    user_id, ticker = test_user_and_ticker
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (user_id, ticker, alert_type, message, severity) "
                "VALUES (%s, %s, 'enter', 'test', 'info')",
                (user_id, ticker),
            )
    # signal_detected_at is irrelevant — pass garbage to prove it.
    assert _already_alerted(user_id, ticker, "enter", "9999-12-31") is True


def test_dedupe_blocks_even_when_signal_in_future(test_user_and_ticker):
    """THE BUG: a real signal in the FUTURE used to bypass dedupe.

    Insert an alert with created_at=NOW(). Then call _already_alerted
    with signal_detected_at=10 days in the future — must STILL return
    True (alert was sent recently, regardless of what timestamp the
    signal claims it came from).
    """
    user_id, ticker = test_user_and_ticker
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (user_id, ticker, alert_type, message, severity) "
                "VALUES (%s, %s, 'enter', 'test', 'info')",
                (user_id, ticker),
            )
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    assert _already_alerted(user_id, ticker, "enter", future) is True, (
        "Future-dated signal_detected_at must NOT bypass dedupe. This "
        "was the SDI bug — re-fixing it would re-flood Telegram."
    )


def test_dedupe_allows_new_alert_after_24h(test_user_and_ticker):
    """After 24h, the same alert type CAN fire again — by design,
    daily-scan runs once a day and a fresh signal next day is wanted."""
    user_id, ticker = test_user_and_ticker
    # Backdate the row by 25h so the 24h window doesn't cover it.
    past = datetime.now(timezone.utc) - timedelta(hours=25)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (user_id, ticker, alert_type, message, "
                "severity, created_at) VALUES (%s, %s, 'enter', 'test', 'info', %s)",
                (user_id, ticker, past),
            )
    assert _already_alerted(user_id, ticker, "enter", "any") is False


def test_dedupe_distinguishes_alert_types(test_user_and_ticker):
    """An 'enter' alert today does NOT dedupe an 'exit' alert.
    Different signal categories must fire independently."""
    user_id, ticker = test_user_and_ticker
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (user_id, ticker, alert_type, message, severity) "
                "VALUES (%s, %s, 'enter', 'test', 'info')",
                (user_id, ticker),
            )
    assert _already_alerted(user_id, ticker, "enter", "any") is True
    assert _already_alerted(user_id, ticker, "exit", "any") is False
