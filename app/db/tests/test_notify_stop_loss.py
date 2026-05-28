"""Unit tests for notify_stop_loss formatter (no DB / no Telegram).

Threshold + dedup + Telegram I/O integration is exercised in the
weekly-scan workflow + monitored via notify_admin_cron alerts.
This file covers the pure formatter to guard the message copy.
"""
from __future__ import annotations

from app.db.notify_stop_loss import format_sl_message


def test_sl_message_includes_drop_pct() -> None:
    msg = format_sl_message(
        name="삼성전자", ticker="005930.KS",
        entry_price=70_000, close=62_000,
        drop_pct=-11.43, threshold=10.0,
    )
    assert "삼성전자" in msg
    assert "005930.KS" in msg
    assert "-11.43%" in msg
    assert "임계 -10" in msg
    # [보유] source tag — alignment with 2026-05-27 telegram redesign.
    assert "[보유]" in msg
    # 다음 단계 — beginner guide block per the no-jargon UX rule.
    assert "다음 단계:" in msg
    # 금요일 종가 reminder — anti panic-trade nudge present on every alert.
    assert "금요일" in msg and "일중 흔들림" in msg
    # Raw signal_type names (volume_case_3 / action_strong_buy / etc) must
    # NOT appear — signal-labels policy (Korean labels only).
    assert "volume_case_3" not in msg
    assert "action_strong_buy" not in msg
    assert "pattern_" not in msg
    assert "/stocks/005930.KS" in msg


def test_sl_message_displays_prices_with_thousand_separators() -> None:
    msg = format_sl_message(
        name="현대차", ticker="005380.KS",
        entry_price=250_000, close=210_000,
        drop_pct=-16.0, threshold=10.0,
    )
    assert "250,000" in msg
    assert "210,000" in msg
