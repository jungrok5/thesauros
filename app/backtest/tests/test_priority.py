"""Same-day BUY priority by signal strength.

Phase 4.6: when multiple BUY candidates fire on the same date and
the slot count is limited, the strongest signal should claim the
slot first (rather than arbitrary insertion order).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest import portfolio as P


def _mkbuy(ticker: str, signal: str, strength: float,
           entry: str = "2023-01-06", exit_iso: str = "2023-03-03",
           entry_p: float = 100, exit_p: float = 110) -> dict:
    return {
        "ticker": ticker, "signal_type": signal,
        "direction": "bullish",
        "entry_date": entry, "exit_date": exit_iso,
        "entry_price": entry_p, "exit_price": exit_p,
        "return_pct": (exit_p / entry_p - 1) * 100,
        "effective_return_pct": (exit_p / entry_p - 1) * 100,
        "hold_weeks": 8, "strength": strength, "timeframe": "weekly",
    }


def test_same_day_strong_buy_wins_slot(monkeypatch) -> None:
    """Two same-day BUYs, max_positions=1. action_strong_buy (0.85)
    should take the slot over pattern_double_bottom (0.55), regardless
    of which appears first in the candidate list."""
    # Reverse order in the list — strong appears AFTER weak.
    cands = [
        _mkbuy("WEAK", "pattern_double_bottom", 0.55),
        _mkbuy("STRONG", "action_strong_buy", 0.85),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
    )
    assert len(state.trades) == 1
    assert state.trades[0].ticker == "STRONG"
    assert state.trades[0].signal_type == "action_strong_buy"


def test_same_day_priority_order_natural_list(monkeypatch) -> None:
    """Strong first in list — still wins (sanity)."""
    cands = [
        _mkbuy("STRONG", "action_strong_buy", 0.85),
        _mkbuy("WEAK", "action_buy", 0.70),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
    )
    assert state.trades[0].ticker == "STRONG"


def test_different_days_no_reordering(monkeypatch) -> None:
    """Different days → priority doesn't apply. First-come takes slot."""
    cands = [
        _mkbuy("EARLY_WEAK", "pattern_double_bottom", 0.55,
               entry="2023-01-06", exit_iso="2023-03-03"),
        _mkbuy("LATE_STRONG", "action_strong_buy", 0.85,
               entry="2023-02-10", exit_iso="2023-04-07"),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
    )
    # Only EARLY_WEAK trades — LATE_STRONG blocked while EARLY is held.
    assert len(state.trades) == 1
    assert state.trades[0].ticker == "EARLY_WEAK"


def test_same_day_three_candidates_two_slots(monkeypatch) -> None:
    """3 fires same day, max=2: top-2 strength wins."""
    cands = [
        _mkbuy("MID", "action_buy", 0.70),
        _mkbuy("STRONG", "action_strong_buy", 0.85),
        _mkbuy("WEAK", "pattern_double_bottom", 0.55),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
    )
    tickers = {t.ticker for t in state.trades}
    assert tickers == {"STRONG", "MID"}     # WEAK blocked
    assert "WEAK" not in tickers


def test_priority_tied_strength_stable(monkeypatch) -> None:
    """Two same-day BUYs with identical strength — both make it in if
    slots allow. Doesn't matter which one comes first."""
    cands = [
        _mkbuy("A", "action_buy", 0.70),
        _mkbuy("B", "action_buy", 0.70),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
    )
    assert {t.ticker for t in state.trades} == {"A", "B"}
