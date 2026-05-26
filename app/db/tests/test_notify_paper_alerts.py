"""Pin the alert-routing logic in app.db.notify_paper_alerts.

Pure-function level — the worker pulls rows from DB, but the
message formatting + the stop-vs-target priority + the
idempotency stamping live in functions we can exercise without
spinning up a real connection.

The smoke test (DB-backed) calling the live SQL is intentionally
omitted here — it would need a paper_trades fixture and a bars
fixture, and the existing daily-data CI green run is itself a
better integration check.
"""
from datetime import datetime, timezone

from app.db.notify_paper_alerts import _format_message


def _position(entry: float, cur: float, **kw) -> dict:
    """Mimics the dict shape `_fetch_open_unalerted` returns from the
    new paper_positions / paper_fills schema."""
    base = {
        "id": "pos-1",
        "user_id": "user-1",
        "ticker": "005990.KQ",
        "initial_entry_price": entry,
        "current_price": cur,
        "initial_stop_loss": entry * 0.9,
        "initial_target": entry * 1.2,
        "total_invested_krw": 1_000_000,
        "shares_open": 1_000_000 / entry,
        "stop_alerted": False,
        "target_alerted": False,
    }
    base.update(kw)
    return base


def test_stop_message_names_the_book_rule():
    """Stop-loss alert must call out the book's 10MA rule + the
    realized loss so the user has the data to decide instantly."""
    msg = _format_message("stop", _position(entry=10_000, cur=8_700))
    assert "005990.KQ" in msg
    assert "손절선" in msg
    assert "10MA" in msg
    # P&L should be negative around -13%
    assert "-13.0%" in msg


def test_target_message_recommends_partial_take_profit():
    """Target alert is informational — book says hold while the
    trend is alive, take some off. Message should reflect both."""
    msg = _format_message("target", _position(entry=10_000, cur=12_500))
    assert "🎯" in msg
    assert "목표가" in msg
    assert "일부 익절" in msg
    # P&L positive
    assert "+25.0%" in msg


def test_messages_link_to_paper_page():
    """Both alerts must point the user to /paper to act — without
    a link the message is a dead-end notification."""
    stop_msg = _format_message("stop", _position(entry=10_000, cur=8_700))
    target_msg = _format_message("target", _position(entry=10_000, cur=12_500))
    assert "/paper" in stop_msg
    assert "/paper" in target_msg
