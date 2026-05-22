"""Unit tests for app.backtest.portfolio.

Focus: state-machine correctness (cash/positions/trades) under buy/
sell events. Mocks `_last_close_or_na` to avoid DB hits.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.backtest import portfolio as P


def _mkcand(ticker: str, entry_iso: str, exit_iso: str,
            entry_p: float, exit_p: float,
            signal_type: str = "action_buy",
            direction: str = "bullish") -> dict:
    return {
        "ticker": ticker,
        "signal_type": signal_type,
        "direction": direction,
        "entry_date": entry_iso,
        "exit_date": exit_iso,
        "entry_price": entry_p,
        "exit_price": exit_p,
        "return_pct": (exit_p / entry_p - 1) * 100.0,
        "effective_return_pct": (exit_p / entry_p - 1) * 100.0,
        "hold_weeks": 8,
        "strength": 0.7,
        "timeframe": "weekly",
    }


# ─────────────────────────────────────────────────────────────────────
# filter_entry_fires
# ─────────────────────────────────────────────────────────────────────

def test_filter_only_bullish_in_whitelist() -> None:
    fires = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 120),  # action_buy bullish
        _mkcand("B", "2023-01-06", "2023-03-03", 50, 60,
                signal_type="pattern_double_top", direction="bearish"),
        _mkcand("C", "2023-01-13", "2023-03-10", 200, 220,
                signal_type="pattern_double_bottom"),
        _mkcand("D", "2023-01-20", "2023-03-17", 30, 32,
                signal_type="volume_case_4", direction="bearish"),
    ]
    out = P.filter_entry_fires(
        fires, entry_signals=["action_buy", "pattern_double_bottom"]
    )
    assert {f["ticker"] for f in out} == {"A", "C"}


def test_filter_dedups_same_ticker_same_date() -> None:
    """If two whitelist signals fire at the same bar, count once."""
    fires = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 110,
                signal_type="action_buy"),
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 110,
                signal_type="pattern_double_bottom"),
    ]
    out = P.filter_entry_fires(
        fires, entry_signals=["action_buy", "pattern_double_bottom"]
    )
    assert len(out) == 1
    assert out[0]["ticker"] == "A"


def test_filter_sorts_by_entry_date() -> None:
    fires = [
        _mkcand("LATE", "2023-06-01", "2023-08-01", 100, 110),
        _mkcand("EARLY", "2023-01-06", "2023-03-03", 50, 55),
    ]
    out = P.filter_entry_fires(fires, ["action_buy"])
    assert [f["ticker"] for f in out] == ["EARLY", "LATE"]


# ─────────────────────────────────────────────────────────────────────
# simulate — state machine basics
# ─────────────────────────────────────────────────────────────────────

def test_simulate_no_candidates_no_change() -> None:
    state = P.simulate(
        [], date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000,
    )
    assert state.cash == 1_000_000
    assert not state.positions
    assert not state.trades


def test_simulate_single_winning_trade(monkeypatch) -> None:
    """One buy + one sell — verify trade P&L includes both fees.

    Buy 100원 share, sell 200원, with 0.015% buy fee + 0.18% sell fee.
    initial_cash 1,000,000, max_pos 1 → full allocation to single position.
    """
    cand = _mkcand("X", "2023-01-06", "2023-03-03", 100.0, 200.0)
    # Mock _last_close_or_na so end-cap doesn't hit DB.
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        [cand], date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
    )
    assert len(state.trades) == 1
    t = state.trades[0]
    # Buy: 1,000,000 (allocation). Net of buy fee = 1,000,000 / 1.00015.
    # Shares = net / 100. PnL roughly = (200-100)/100 = +100% before fees.
    # After fees ~ +99.7%-ish.
    assert t.pnl_pct > 95.0
    assert t.pnl_pct < 100.0
    assert state.cash > state.initial_cash      # made money


def test_simulate_max_positions_blocks_excess(monkeypatch) -> None:
    """3 buy candidates, max_pos = 2 → 3rd buy declined."""
    cands = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 110),
        _mkcand("B", "2023-01-13", "2023-03-10", 50, 55),
        _mkcand("C", "2023-01-20", "2023-03-17", 200, 220),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
    )
    # 2 trades closed (A, B). C never bought.
    closed_tickers = {t.ticker for t in state.trades}
    assert "A" in closed_tickers
    assert "B" in closed_tickers
    assert "C" not in closed_tickers


def test_simulate_same_ticker_not_double_bought(monkeypatch) -> None:
    """Ticker A fires twice with overlapping windows → only the first
    BUY is taken. The second is dropped (already held)."""
    cands = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 110),
        _mkcand("A", "2023-01-20", "2023-03-17", 105, 115),  # while still holding
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=5,
    )
    # First buy taken, second buy declined (already held). One trade total.
    assert len(state.trades) == 1
    assert state.trades[0].entry_date == date(2023, 1, 6)


def test_simulate_sell_frees_slot_for_subsequent_buy(monkeypatch) -> None:
    """A sells on 2023-03-03 freeing slot; B buys on 2023-03-10 (after)."""
    cands = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 110),
        _mkcand("B", "2023-03-10", "2023-05-05", 200, 230),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
    )
    closed = {t.ticker for t in state.trades}
    assert closed == {"A", "B"}


def test_simulate_skips_candidate_before_start_date(monkeypatch) -> None:
    """Candidate with entry_date < start should be ignored (no warmup)."""
    cands = [
        _mkcand("PRE", "2022-11-01", "2022-12-31", 100, 110),
        _mkcand("POST", "2023-02-01", "2023-04-01", 200, 220),
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
    )
    tickers = {t.ticker for t in state.trades}
    assert "PRE" not in tickers
    assert "POST" in tickers


def test_simulate_costs_reduce_winning_trade_pnl(monkeypatch) -> None:
    """A 'flat' trade (entry == exit) should yield NEGATIVE pnl
    because of buy+sell fees. Demonstrates costs are actually applied."""
    cand = _mkcand("X", "2023-01-06", "2023-03-03", 100.0, 100.0)
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        [cand], date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        buy_cost_pct=0.001, sell_cost_pct=0.002,
    )
    assert len(state.trades) == 1
    assert state.trades[0].pnl_pct < 0     # fees ate the trade


# ─────────────────────────────────────────────────────────────────────
# summarize
# ─────────────────────────────────────────────────────────────────────

def test_summarize_no_trades() -> None:
    s = P.PortfolioState(cash=1_000_000, initial_cash=1_000_000)
    summary = P.summarize(s)
    assert summary["n_trades"] == 0


def test_summarize_basic(monkeypatch) -> None:
    cands = [
        _mkcand("A", "2023-01-06", "2023-03-03", 100, 120),  # +20%
        _mkcand("B", "2023-03-10", "2023-05-05", 100, 90),   # -10%
        _mkcand("C", "2023-05-12", "2023-07-07", 100, 130),  # +30%
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=1,
        buy_cost_pct=0, sell_cost_pct=0,        # remove costs for clean math
    )
    s = P.summarize(state)
    assert s["n_trades"] == 3
    assert s["win_rate"] == pytest.approx(2/3)
    # 2 winners (20%, 30%), 1 loser (-10%). payoff = mean(20,30)/10 = 25/10 = 2.5
    assert s["payoff"] == pytest.approx(2.5)
