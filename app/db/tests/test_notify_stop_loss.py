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
    assert "임계: -10" in msg
    # Korean book quote
    assert "손절은 빠르게" in msg
    assert "/stocks/005930.KS" in msg


def test_sl_message_displays_prices_with_thousand_separators() -> None:
    msg = format_sl_message(
        name="현대차", ticker="005380.KS",
        entry_price=250_000, close=210_000,
        drop_pct=-16.0, threshold=10.0,
    )
    assert "250,000" in msg
    assert "210,000" in msg
