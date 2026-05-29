"""Telegram ALERT_RULES ↔ backtest / screener signal alignment.

Origin: 2026-05-26 site-review. The Telegram worker only mapped
action_strong_buy + action_buy to 'enter' alerts, but the screener
treats universe-winning signals (volume_case_3, pattern_forking,
volume_case_7, pattern_ma240_breakout, action_strong_buy) as primary
buy candidates — subscribed users were missing 4 of the 5 signals
they could see on the site.

These tests lock the alignment: every backtest DEFAULT_ENTRY_SIGNALS
entry must classify as 'enter' (severity 'info'), so the user sees
the same buy candidates in the backtest / screener / Telegram inbox
(one algorithm, three faces — memory project_book_faithful_backtest).

2026-05-27: BookEntrySpots dashboard card was removed; /screener is
the only candidate surface, alignment goal unchanged.
2026-05-29: action_buy removed from this set after Phase 10 alignment
audit. The backtest's DEFAULT_ENTRY_SIGNALS never included action_buy
(low payoff vs the top-5); Telegram alerting on it broke the "one
algorithm" invariant. Now five signals exactly match backtest.
"""
from __future__ import annotations

from app.db.telegram_worker import classify
# Pull from backtest portfolio module so this test detects any
# divergence at the import boundary — if someone changes
# DEFAULT_ENTRY_SIGNALS without updating ALERT_RULES, the test below
# fails immediately.
from app.backtest.portfolio import DEFAULT_ENTRY_SIGNALS


UNIVERSE_TOP5_ENTRY_SIGNALS = list(DEFAULT_ENTRY_SIGNALS)


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


def test_action_buy_does_not_fire_enter_alert():
    """action_buy is intentionally NOT in DEFAULT_ENTRY_SIGNALS (low
    payoff vs the top-5). Telegram must not alert on it as an entry
    signal — the screener won't show it either."""
    assert classify("action_buy") is None, (
        "action_buy was retired from the 'enter' tier on 2026-05-29 to "
        "match the backtest's DEFAULT_ENTRY_SIGNALS. If someone re-adds "
        "it to ALERT_RULES, this guard fails."
    )
