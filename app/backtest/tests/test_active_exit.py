"""Active-exit logic tests for portfolio.simulate.

Book p260-265: 쌍봉/저승사자 / 10MA 깨짐 = 즉시 청산. Phase 4.5 lets
bearish signals fire mid-hold and close the position early.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest import portfolio as P


def _mkbuy(ticker: str, entry: str, exit: str,
           entry_p: float, exit_p: float,
           signal_type: str = "action_buy") -> dict:
    return {
        "ticker": ticker, "signal_type": signal_type,
        "direction": "bullish",
        "entry_date": entry, "exit_date": exit,
        "entry_price": entry_p, "exit_price": exit_p,
        "return_pct": (exit_p / entry_p - 1) * 100,
        "effective_return_pct": (exit_p / entry_p - 1) * 100,
        "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly",
    }


def _mksell(ticker: str, fire_date: str, fire_price: float,
            signal_type: str = "pattern_double_top") -> dict:
    """A bearish-signal fire (the form filter_exit_fires returns)."""
    return {
        "ticker": ticker, "signal_type": signal_type,
        "direction": "bearish",
        "entry_date": fire_date,   # fire date
        "exit_date": fire_date,    # n/a for exit fires
        "entry_price": fire_price, # sell at this close
        "exit_price": fire_price,
        "return_pct": 0.0, "effective_return_pct": 0.0,
        "hold_weeks": 8, "strength": 0.8, "timeframe": "weekly",
    }


# ─────────────────────────────────────────────────────────────────────
# filter_exit_fires
# ─────────────────────────────────────────────────────────────────────

def test_filter_exit_keeps_only_bearish_whitelist() -> None:
    fires = [
        _mksell("A", "2023-03-01", 90, "pattern_double_top"),     # ✓
        _mksell("B", "2023-03-08", 80, "pattern_triple_top"),     # ✓
        _mksell("C", "2023-03-15", 70, "volume_case_4"),          # ✗ not in whitelist
        _mkbuy("D", "2023-03-22", "2023-05-19", 100, 110),         # ✗ bullish
    ]
    out = P.filter_exit_fires(
        fires, ["pattern_double_top", "pattern_triple_top"]
    )
    assert {f["ticker"] for f in out} == {"A", "B"}


def test_filter_exit_dedups_same_bar() -> None:
    """Two bearish signals on same (ticker, date) → single exit event."""
    fires = [
        _mksell("A", "2023-03-01", 90, "pattern_double_top"),
        _mksell("A", "2023-03-01", 90, "action_sell_short"),
    ]
    out = P.filter_exit_fires(
        fires, ["pattern_double_top", "action_sell_short"]
    )
    assert len(out) == 1


# ─────────────────────────────────────────────────────────────────────
# Active exit overrides planned 8-week exit
# ─────────────────────────────────────────────────────────────────────

def test_active_exit_closes_position_early(monkeypatch) -> None:
    """Buy on 2023-01-06, planned exit 2023-03-03 (8w). Active sell
    fires on 2023-02-10 at lower price. Trade closes 2023-02-10."""
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 130)]
    exits = [_mksell("A", "2023-02-10", 110, "pattern_double_top")]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits,
    )
    assert len(state.trades) == 1
    t = state.trades[0]
    assert t.exit_date == date(2023, 2, 10)
    assert t.exit_price == 110.0
    # Tag with both entry + exit signal for diagnostic.
    assert "action_buy" in t.signal_type
    assert "pattern_double_top" in t.signal_type


def test_active_exit_only_fires_for_held_tickers(monkeypatch) -> None:
    """Bearish fire for a ticker we don't hold → no-op."""
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 110)]
    exits = [_mksell("B", "2023-02-10", 50, "pattern_double_top")]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits,
    )
    # A still exits on its planned date (no active exit for it).
    assert len(state.trades) == 1
    assert state.trades[0].ticker == "A"
    assert state.trades[0].exit_date == date(2023, 3, 3)


def test_active_exit_frees_slot_for_subsequent_buy(monkeypatch) -> None:
    """Active exit closes A on 2023-02-10, freeing a slot. B fires
    on 2023-02-17 → takes the slot. With fixed 8w hold, A would not
    have exited until 2023-03-03 and B's BUY would have been blocked
    (max=1)."""
    cands = [
        _mkbuy("A", "2023-01-06", "2023-03-03", 100, 110),
        _mkbuy("B", "2023-02-17", "2023-04-14", 200, 230),
    ]
    exits = [_mksell("A", "2023-02-10", 95)]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits,
    )
    closed_tickers = {t.ticker for t in state.trades}
    assert closed_tickers == {"A", "B"}


def test_active_exit_disabled_without_exit_fires(monkeypatch) -> None:
    """Without exit_fires (default None), fixed-hold behavior."""
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 110)]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        # exit_fires not passed
    )
    assert len(state.trades) == 1
    assert state.trades[0].exit_date == date(2023, 3, 3)


def test_active_exit_after_planned_exit_no_double_close(monkeypatch) -> None:
    """Bearish fire AFTER position already closed → no-op."""
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 110)]
    exits = [_mksell("A", "2023-04-01", 105)]   # after planned exit
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits,
    )
    # Only one trade — planned exit fired first.
    assert len(state.trades) == 1
    assert state.trades[0].exit_date == date(2023, 3, 3)


def test_active_exit_position_entry_signal_preserved(monkeypatch) -> None:
    """The Trade.signal_type should record BOTH entry and exit signals
    when active exit fires — diagnostic value."""
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 130,
                    signal_type="action_strong_buy")]
    exits = [_mksell("A", "2023-02-03", 95, "action_sell_short")]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits,
    )
    sig = state.trades[0].signal_type
    assert "action_strong_buy" in sig
    assert "action_sell_short" in sig
