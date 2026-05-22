"""Regression tests for the 와병투자 (bedrest) mode short-circuit.

Background — book 2부 3장: "한달 내내 누워있다 말일 1회만 확인". If a
user opts into bedrest_mode, telegram_worker MUST not emit any alert
for them, regardless of the per-alert toggles or the eligibility gate.
Only the (future) weekly digest path is allowed to reach them.

These tests pin the gate before the regression sneaks back.
"""
from __future__ import annotations

from unittest.mock import patch

from app.db import telegram_worker


def _user_row(bedrest: bool, **extra) -> dict:
    base = {
        "enable_enter": True, "enable_pyramid": True, "enable_warn": True,
        "enable_exit": True, "enable_ma240_break": True,
        "enable_quarter_25_break": True,
        "bedrest_mode": bedrest,
    }
    base.update(extra)
    return base


def test_bedrest_user_is_skipped_in_run_once():
    """User with bedrest_mode=True must not even reach the per-alert
    loop — run_once short-circuits at the prefs check."""
    user = {"id": "user-1", "telegram_chat_id": "111", "has_push": False}
    watch = [{"ticker": "005930.KS", "category": "holding"}]

    with patch.object(telegram_worker, "_users_with_alerts", return_value=[user]):
        with patch.object(telegram_worker, "_watchlist_active", return_value=watch):
            with patch.object(telegram_worker, "_user_prefs",
                              return_value=_user_row(bedrest=True)):
                with patch.object(telegram_worker, "_active_signals_for") as mock_signals:
                    with patch.object(telegram_worker, "_check_price_targets") as mock_targets:
                        stats = telegram_worker.run_once(dry_run=True)

    # Bedrest user → no signals fetched, no price-targets checked, no alerts.
    assert mock_signals.call_count == 0, (
        "bedrest_mode must short-circuit before _active_signals_for"
    )
    assert mock_targets.call_count == 0, (
        "bedrest_mode must short-circuit before _check_price_targets"
    )
    assert stats["new_alerts"] == 0
    assert stats["sent"] == 0
    assert stats["bedrest_skipped"] == 1


def test_non_bedrest_user_proceeds_normally():
    """Sanity check — disabling bedrest doesn't accidentally skip the
    normal path."""
    user = {"id": "user-1", "telegram_chat_id": "111", "has_push": False}
    watch = [{"ticker": "005930.KS", "category": "holding"}]

    with patch.object(telegram_worker, "_users_with_alerts", return_value=[user]):
        with patch.object(telegram_worker, "_watchlist_active", return_value=watch):
            with patch.object(telegram_worker, "_user_prefs",
                              return_value=_user_row(bedrest=False)):
                # Return no signals to keep the test focused on gate
                # behavior, not message rendering.
                with patch.object(telegram_worker, "_active_signals_for",
                                   return_value=[]) as mock_signals:
                    with patch.object(telegram_worker, "_check_price_targets",
                                       return_value=[]) as mock_targets:
                        stats = telegram_worker.run_once(dry_run=True)

    # Non-bedrest: per-ticker path runs (even if it finds no signals).
    assert mock_signals.call_count >= 1, (
        "non-bedrest users must reach the signal-lookup path"
    )
    assert mock_targets.call_count >= 1
    assert stats["bedrest_skipped"] == 0


def test_user_prefs_default_bedrest_off_when_row_missing():
    """A user without an alert_preferences row must default to bedrest
    OFF — otherwise the system silently muzzles users who never
    visited /settings/alerts."""
    # Use a fake DB stub to simulate the missing-row case.
    from unittest.mock import MagicMock

    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.description = []
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch.object(telegram_worker, "get_conn", return_value=conn):
        prefs = telegram_worker._user_prefs("nonexistent-user")

    assert prefs["bedrest_mode"] is False, (
        "default prefs must NOT silently turn bedrest on"
    )
    # And other toggles default to ON (all-on default semantics).
    assert prefs["enable_enter"] is True
    assert prefs["enable_exit"] is True
