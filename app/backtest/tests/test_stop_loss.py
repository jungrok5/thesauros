"""Stop-loss exit logic tests.

Phase 4.7: a position whose weekly close drops by ≥ stop_loss_pct
from entry should close at that breach bar's close (NOT at planned
exit). Same processing slot as ACTIVE_EXIT, just from price-based
trigger instead of bearish signal.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.backtest import portfolio as P


def _mkbuy(ticker: str, entry: str, exit_iso: str,
           entry_p: float, exit_p: float,
           signal: str = "action_buy") -> dict:
    return {
        "ticker": ticker, "signal_type": signal,
        "direction": "bullish",
        "entry_date": entry, "exit_date": exit_iso,
        "entry_price": entry_p, "exit_price": exit_p,
        "return_pct": (exit_p / entry_p - 1) * 100,
        "effective_return_pct": (exit_p / entry_p - 1) * 100,
        "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly",
    }


def _stub_bars(closes_by_date: dict) -> pd.DataFrame:
    """Build a weekly bars DataFrame from {date: close} dict."""
    rows = sorted(closes_by_date.items())
    df = pd.DataFrame([
        {"date": pd.Timestamp(d), "open": c, "high": c, "low": c,
         "close": c, "adj_close": c, "volume": 1_000_000}
        for d, c in rows
    ])
    return df


# ─────────────────────────────────────────────────────────────────────
# _build_stop_loss_events
# ─────────────────────────────────────────────────────────────────────

def test_stop_loss_event_emitted_at_first_breach(monkeypatch) -> None:
    """Entry @100, stop-loss 15%. Bars dip to 80 on 2nd Friday → STOP_LOSS event."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 95,
        date(2023, 1, 20): 80, date(2023, 1, 27): 70,  # breach week 3
        date(2023, 2, 3): 60, date(2023, 2, 10): 50,
    })
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 60)]
    events = P._build_stop_loss_events(
        cands, stop_loss_pct=0.15,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert len(events) == 1
    ev_date, kind, ticker, price, _idx, _strength = events[0]
    assert kind == "STOP_LOSS"
    assert ticker == "A"
    assert ev_date == date(2023, 1, 20)   # first breach
    assert price == 80


def test_no_stop_loss_if_never_breaches(monkeypatch) -> None:
    """Bars stay above threshold → no STOP_LOSS event."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 102,
        date(2023, 1, 20): 95, date(2023, 1, 27): 92,
        date(2023, 2, 3): 90, date(2023, 2, 10): 95,
    })
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    cands = [_mkbuy("A", "2023-01-06", "2023-02-10", 100, 95)]
    events = P._build_stop_loss_events(
        cands, stop_loss_pct=0.15,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert events == []


def test_stop_loss_takes_priority_over_planned_exit(monkeypatch) -> None:
    """Position drops below stop-loss on week 3, planned exit week 8.
    Trade should close on week 3 at breach price."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 95,
        date(2023, 1, 20): 80,   # breach (-20%)
        date(2023, 1, 27): 70, date(2023, 2, 3): 65,
        date(2023, 2, 10): 110, date(2023, 2, 17): 120,
        date(2023, 2, 24): 130, date(2023, 3, 3): 140,
    })
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 140)]
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        stop_loss_pct=0.15,
    )
    assert len(state.trades) == 1
    t = state.trades[0]
    assert t.exit_date == date(2023, 1, 20)
    assert t.exit_price == 80
    # Stop-loss tag in signal_type
    assert "stop_loss" in t.signal_type


def test_stop_loss_disabled_when_pct_zero(monkeypatch) -> None:
    """stop_loss_pct=0 → no STOP_LOSS events. Planned exit still applies."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 20): 50,
        date(2023, 3, 3): 90,
    })
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 90)]
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        stop_loss_pct=0.0,
    )
    assert state.trades[0].exit_date == date(2023, 3, 3)
    assert "stop_loss" not in state.trades[0].signal_type


def test_stop_loss_only_for_held_position(monkeypatch) -> None:
    """If position was already closed (e.g., by active exit), the
    STOP_LOSS event is a no-op."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 95,
        date(2023, 1, 20): 80,  # breach
        date(2023, 1, 27): 70, date(2023, 2, 3): 65,
    })
    cands = [_mkbuy("A", "2023-01-06", "2023-02-03", 100, 65)]
    # Active exit fires earlier on 2023-01-13 at 95
    exits = [{
        "ticker": "A", "signal_type": "pattern_double_top",
        "direction": "bearish",
        "entry_date": "2023-01-13", "exit_date": "2023-01-13",
        "entry_price": 95, "exit_price": 95,
        "return_pct": -5, "effective_return_pct": 5,
        "hold_weeks": 8, "strength": 0.8, "timeframe": "weekly",
    }]
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        exit_fires=exits, stop_loss_pct=0.15,
    )
    # Should close ONCE at active exit (no double close).
    assert len(state.trades) == 1
    assert state.trades[0].exit_date == date(2023, 1, 13)
    assert "pattern_double_top" in state.trades[0].signal_type


# ─────────────────────────────────────────────────────────────────────
# _build_trailing_stop_events
# ─────────────────────────────────────────────────────────────────────

def test_trailing_stop_triggers_after_peak(monkeypatch) -> None:
    """Entry @100, price climbs to 130, then drops to 117 (10% below peak)
    → TRAILING_STOP event at 117."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 110,
        date(2023, 1, 20): 130,                  # peak
        date(2023, 1, 27): 125,                  # -3.8% from peak — no fire
        date(2023, 2, 3): 116,                   # < 130*0.9=117 — FIRE
        date(2023, 2, 10): 110,
    })
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 110)]
    events = P._build_trailing_stop_events(
        cands, trailing_stop_pct=0.10,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert len(events) == 1
    ev_date, kind, ticker, price, _idx, _strength = events[0]
    assert kind == "TRAILING_STOP"
    assert ev_date == date(2023, 2, 3)
    assert price == 116


def test_trailing_stop_no_fire_if_only_climbs(monkeypatch) -> None:
    """If price never drops 10% below the running peak, no fire."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 105,
        date(2023, 1, 20): 110, date(2023, 1, 27): 115,
        date(2023, 2, 3): 120, date(2023, 2, 10): 130,
    })
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    cands = [_mkbuy("A", "2023-01-06", "2023-02-10", 100, 130)]
    events = P._build_trailing_stop_events(
        cands, trailing_stop_pct=0.10,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert events == []


def test_trailing_stop_fires_below_entry_too(monkeypatch) -> None:
    """Trailing stop ALSO catches drops below entry — initial peak =
    entry_price, so a 10% drop from entry without a higher peak is
    equivalent to a flat stop."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 95,
        date(2023, 1, 20): 88,                   # -12% from 100 entry/peak
        date(2023, 1, 27): 80,
    })
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    cands = [_mkbuy("A", "2023-01-06", "2023-02-10", 100, 80)]
    events = P._build_trailing_stop_events(
        cands, trailing_stop_pct=0.10,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert len(events) == 1
    ev_date, _kind, _t, price, *_ = events[0]
    assert ev_date == date(2023, 1, 20)
    assert price == 88


def test_trailing_stop_in_simulate_closes_with_tag(monkeypatch) -> None:
    """End-to-end: simulate with trailing_stop_pct should close the
    position at the trailing-stop bar with 'trailing_stop' tag."""
    bars = _stub_bars({
        date(2023, 1, 6): 100, date(2023, 1, 13): 110,
        date(2023, 1, 20): 130,                  # peak
        date(2023, 1, 27): 116,                  # -10.8% from peak
        date(2023, 2, 3): 110, date(2023, 2, 10): 105,
        date(2023, 2, 17): 100, date(2023, 2, 24): 95,
        date(2023, 3, 3): 90,
    })
    cands = [_mkbuy("A", "2023-01-06", "2023-03-03", 100, 90)]
    monkeypatch.setattr(
        "app.backtest.local_store.load_bars",
        lambda t, g: bars,
    )
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        trailing_stop_pct=0.10,
    )
    assert len(state.trades) == 1
    t = state.trades[0]
    assert t.exit_date == date(2023, 1, 27)
    assert t.exit_price == 116
    assert "trailing_stop" in t.signal_type


def test_trailing_stop_caches_bars_per_ticker(monkeypatch) -> None:
    """Same-ticker candidates must share bars cache (perf sanity)."""
    call_count = {"n": 0}

    def counting_load(t, g):
        call_count["n"] += 1
        return _stub_bars({
            date(2023, 1, 6): 100, date(2023, 1, 13): 120,
            date(2023, 1, 20): 100,
        })

    monkeypatch.setattr("app.backtest.local_store.load_bars", counting_load)

    cands = [
        _mkbuy("A", "2023-01-06", "2023-02-03", 100, 100),
        _mkbuy("A", "2023-02-10", "2023-03-10", 100, 100),
        _mkbuy("A", "2023-04-07", "2023-05-05", 100, 100),
    ]
    P._build_trailing_stop_events(
        cands, trailing_stop_pct=0.10,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert call_count["n"] == 1


def test_stop_loss_caches_bars_per_ticker(monkeypatch) -> None:
    """Multiple candidates of the same ticker should hit load_bars
    once (in-builder cache). Sanity for perf at scale."""
    call_count = {"n": 0}

    def counting_load(t, g):
        call_count["n"] += 1
        return _stub_bars({date(2023, 1, 6): 100, date(2023, 1, 13): 80})

    monkeypatch.setattr("app.backtest.local_store.load_bars", counting_load)

    cands = [
        _mkbuy("A", "2023-01-06", "2023-02-03", 100, 80),
        _mkbuy("A", "2023-02-10", "2023-03-10", 100, 80),
        _mkbuy("A", "2023-04-07", "2023-05-05", 100, 80),
    ]
    P._build_stop_loss_events(
        cands, stop_loss_pct=0.15,
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    assert call_count["n"] == 1   # cached across the 3 candidates
