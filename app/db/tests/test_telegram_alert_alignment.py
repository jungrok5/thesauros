"""Telegram ALERT_RULES ↔ /screener signal alignment.

Origin: 2026-05-26 site-review. The Telegram worker only mapped
action_strong_buy + action_buy to 'enter' alerts, but the screener
treats universe-winning signals (volume_case_3, pattern_forking,
volume_case_7, pattern_ma240_breakout, action_strong_buy) as primary
buy candidates — subscribed users were missing 4 of the 5 signals
they could see on the site.

These tests lock the alignment: every universe-winner book-spirit
entry signal must classify as 'enter' (severity 'info'), so the user
sees the same buy candidates in the screener and in their Telegram
inbox.

2026-05-27: BookEntrySpots dashboard card was removed; /screener is
the only candidate surface, alignment goal unchanged.
"""
from __future__ import annotations

from app.db.telegram_worker import classify


# The 5 signals /screener treats as primary buy candidates (production
# winner config from sweep_per_signal_sl + book-spirit backtest top-5).
UNIVERSE_TOP5_ENTRY_SIGNALS = [
    "action_strong_buy",
    "action_buy",                # screener actionIn includes this
    "volume_case_3",             # 바닥 폭증 (book p365-369)
    "volume_case_7",             # 매집 감소 (book "급등초기")
    "pattern_forking",           # 포킹 (책: 강한 매집 자리)
    "pattern_ma240_breakout",    # 240MA 돌반지 (PSK 패턴)
]


def test_all_universe_top5_signals_map_to_enter():
    for sig in UNIVERSE_TOP5_ENTRY_SIGNALS:
        result = classify(sig)
        assert result is not None, (
            f"signal {sig!r} is unclassified — universe-winner signal "
            f"must reach Telegram subscribers"
        )
        alert_type, severity = result
        assert alert_type == "enter", (
            f"signal {sig!r} → alert_type={alert_type!r}, expected 'enter' "
            f"(/screener shows this as a buy candidate)"
        )
        assert severity == "info", (
            f"signal {sig!r} → severity={severity!r}, expected 'info'"
        )


def test_warn_class_distinct_from_enter_class():
    """volume_case_9 / volume_case_10 are bearish-leaning (분배 의심 /
    천장 폭증) — must stay in 'warn', not bleed into 'enter'. The
    universe-top-5 additions for volume_case_3 / 7 must not introduce
    a prefix-collision bug that swallows 9/10."""
    for sig in ("volume_case_9", "volume_case_10"):
        result = classify(sig)
        assert result == ("warn", "warn"), (
            f"{sig!r} → {result!r}, expected ('warn','warn')"
        )


def test_action_sell_unchanged():
    """Sell-side classification must survive the universe-top-5
    additions. (Sanity — additions are upstream of these in the rules
    list so first-match would pick enter for STRONG_BUY-prefixed
    types, never for action_sell.)"""
    assert classify("action_sell") == ("exit", "critical")
    assert classify("action_sell_short") == ("exit", "critical")


def test_unknown_signal_returns_none():
    assert classify("unknown_xyz") is None
    assert classify("") is None
