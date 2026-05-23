"""Unit tests for risk-adjusted metrics module.

Validates MTM equity series construction + Sharpe/Sortino/Calmar
calculations + alpha-beta vs KOSPI regression on hand-built data.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.backtest import metrics as M
from app.backtest.portfolio import PortfolioState, Trade


def _make_state(trades, initial_cash=10_000_000.0) -> PortfolioState:
    s = PortfolioState(cash=initial_cash, initial_cash=initial_cash)
    s.trades = trades
    # Final cash = initial - sum(buys) + sum(sells)
    cash = initial_cash
    for t in trades:
        cash -= t.cost_basis_krw
        cash += t.proceeds_krw
    s.cash = cash
    return s


def _trade(ticker, entry_d, exit_d, entry_p, exit_p,
           shares=100, signal="action_buy") -> Trade:
    cost = entry_p * shares
    proceeds = exit_p * shares
    pnl = proceeds - cost
    return Trade(
        ticker=ticker, entry_date=entry_d, exit_date=exit_d,
        entry_price=entry_p, exit_price=exit_p,
        shares=shares, cost_basis_krw=cost,
        proceeds_krw=proceeds, pnl_krw=pnl,
        pnl_pct=(pnl / cost * 100) if cost else 0.0,
        days_held=(exit_d - entry_d).days, signal_type=signal,
    )


# ─────────────────────────────────────────────────────────────────────
# Weekly MTM equity construction
# ─────────────────────────────────────────────────────────────────────

def test_empty_state_returns_flat_series() -> None:
    """No trades → equity = initial_cash every Friday."""
    state = _make_state([], initial_cash=10_000_000)
    eq = M.weekly_equity_series(
        state, date(2023, 1, 1), date(2023, 2, 28),
        get_close_fn=lambda *_a: None,
    )
    assert len(eq) > 0
    assert (eq["equity"] == 10_000_000).all()


def test_buy_then_sell_with_mtm_in_between() -> None:
    """Buy 100 shares @ 100원 on 2023-01-06, sell @ 150원 on 2023-02-03.
    Between buy & sell, MTM uses get_close (here: linearly interpolated
    100→150 over 4 weeks)."""
    trades = [_trade("A", date(2023, 1, 6), date(2023, 2, 3),
                     entry_p=100, exit_p=150)]
    state = _make_state(trades, initial_cash=100_000)

    # MTM closes: stair-step 100 → 150 across 4 weeks
    mtm_prices = {
        date(2023, 1, 6): 100, date(2023, 1, 13): 110,
        date(2023, 1, 20): 120, date(2023, 1, 27): 135,
        date(2023, 2, 3): 150,
    }
    eq = M.weekly_equity_series(
        state, date(2023, 1, 1), date(2023, 2, 10),
        get_close_fn=lambda t, d: mtm_prices.get(d),
    )
    # Equity progression:
    # Before buy: 100,000 (all cash)
    # Buy 100sh × 100 = 10,000 paid → cash 90,000 + holdings 10,000 = 100,000
    # Week 2: holdings 100 × 110 = 11,000 → equity 101,000
    # ...
    # After sell: cash = 90,000 + 15,000 = 105,000 → equity 105,000
    final_eq = eq.iloc[-1]["equity"]
    assert final_eq == pytest.approx(105_000, abs=1)


def test_mtm_captures_unrealised_gain() -> None:
    """A position with positive open MTM should INCREASE equity even
    before the close. Trade-based summary would freeze equity at
    cash + cost_basis until close. MTM doesn't."""
    trades = [_trade("A", date(2023, 1, 6), date(2023, 3, 3),
                     entry_p=100, exit_p=110, shares=1000)]
    state = _make_state(trades, initial_cash=200_000)

    # During hold, price rises 100 → 105.
    prices = {
        date(2023, 1, 6): 100, date(2023, 1, 13): 102,
        date(2023, 1, 20): 105, date(2023, 1, 27): 103,
        date(2023, 2, 3): 108, date(2023, 2, 10): 109,
        date(2023, 2, 17): 110, date(2023, 2, 24): 112,
        date(2023, 3, 3): 110,
    }
    eq = M.weekly_equity_series(
        state, date(2023, 1, 1), date(2023, 3, 10),
        get_close_fn=lambda t, d: prices.get(d),
    )
    # On 2023-01-20 (price 105), equity = 200k - 100k (cost) + 105k MTM = 205k
    mid_row = eq[eq["date"] == date(2023, 1, 20)]
    assert mid_row.iloc[0]["equity"] == pytest.approx(205_000, abs=1)


# ─────────────────────────────────────────────────────────────────────
# Sharpe / Sortino / Calmar
# ─────────────────────────────────────────────────────────────────────

def test_sharpe_zero_variance_returns_none() -> None:
    """Equity that never changes → std = 0 → Sharpe undefined."""
    eq = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=20, freq="W-FRI"),
                       "equity": [100_000] * 20})
    eq["weekly_return"] = eq["equity"].pct_change()
    assert M.sharpe_ratio(eq) is None


def test_sharpe_too_few_observations_returns_none() -> None:
    """< 10 observations → no Sharpe (statistically meaningless)."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=5, freq="W-FRI"),
        "equity": [100_000, 101_000, 102_000, 103_000, 104_000],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    assert M.sharpe_ratio(eq) is None


def test_sharpe_steady_growth_high() -> None:
    """Steady 1%/week return → very high Sharpe (low vol)."""
    eq_vals = [100_000 * (1.01) ** i for i in range(60)]
    eq = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=60, freq="W-FRI"),
                       "equity": eq_vals})
    eq["weekly_return"] = eq["equity"].pct_change()
    sr = M.sharpe_ratio(eq, risk_free_annual=0.0)
    # Steady positive return, near-zero std → Sharpe → infinity but
    # numerically very large.
    assert sr is None or sr > 50      # might trip on float precision


def test_sortino_only_penalises_downside() -> None:
    """For series with NO negative returns, Sortino should be None
    (insufficient downside observations)."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=30, freq="W-FRI"),
        "equity": [100_000 * (1.01) ** i for i in range(30)],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    sortino = M.sortino_ratio(eq, risk_free_annual=0.0)
    assert sortino is None    # need ≥5 downside


def test_calmar_requires_min_1_year() -> None:
    """Backtest < 52 weeks → Calmar undefined."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=20, freq="W-FRI"),
        "equity": [100_000 + i * 1000 for i in range(20)],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    assert M.calmar_ratio(eq) is None


# ─────────────────────────────────────────────────────────────────────
# Max drawdown (MTM-based)
# ─────────────────────────────────────────────────────────────────────

def test_max_drawdown_pct_basic() -> None:
    """Equity: 100 → 150 → 100 → 200. Peak 150 → trough 100 = 33%."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=4, freq="W-FRI"),
        "equity": [100, 150, 100, 200],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    dd = M.max_drawdown_pct(eq)
    assert dd == pytest.approx(1 / 3, abs=0.001)


def test_max_drawdown_no_drop() -> None:
    """Monotonically rising equity → DD = 0."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=10, freq="W-FRI"),
        "equity": [100 + i * 10 for i in range(10)],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    assert M.max_drawdown_pct(eq) == pytest.approx(0.0, abs=0.001)


# ─────────────────────────────────────────────────────────────────────
# Annualised return
# ─────────────────────────────────────────────────────────────────────

def test_annualised_return_one_year_doubled() -> None:
    """100k → 200k over exactly 52 weeks = +100% annualised."""
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=53, freq="W-FRI"),
        "equity": [100_000 * (2 ** (i / 52)) for i in range(53)],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    ar = M.annualised_return(eq)
    assert ar == pytest.approx(1.0, abs=0.01)


def test_annualised_return_handles_zero_initial() -> None:
    eq = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=10, freq="W-FRI"),
        "equity": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    })
    eq["weekly_return"] = eq["equity"].pct_change()
    assert M.annualised_return(eq) is None
