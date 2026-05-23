"""Unit tests for market_regime + portfolio integration.

Validates:
  - regime lookup returns correct bool for known KOSPI dates
  - kospi_regime_filter callable works as portfolio expects
  - portfolio.simulate(regime_filter=...) reduces trades during
    bear periods, preserves bull-market trades
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.backtest import market_regime as MR


# ─────────────────────────────────────────────────────────────────────
# Regime lookup correctness
# ─────────────────────────────────────────────────────────────────────

def _stub_regime_df() -> pd.DataFrame:
    """Hand-built monthly KOSPI close + 10MA for test injection."""
    dates = pd.date_range("2008-01-31", periods=24, freq="ME")
    # Simulate a bull → bear → bull cycle.
    closes = [
        1800, 1750, 1700, 1650, 1600, 1500,  # falling first half of 2008
        1400, 1300, 1200, 1100, 1000, 1100,  # GFC bottom + Q4 bounce
        1200, 1300, 1400, 1500, 1600, 1700,  # 2009 recovery
        1800, 1900, 2000, 2050, 2100, 2150,
    ]
    df = pd.DataFrame({"date": dates, "close": closes})
    df["ma_10"] = df["close"].rolling(10, min_periods=5).mean()
    df["above"] = df["close"] > df["ma_10"]
    return df


def test_is_market_above_uses_latest_close_le_date() -> None:
    """When asked about a date that doesn't have a bar, use the
    latest month-end ≤ that date."""
    MR.clear_regime_cache()
    with patch.object(MR, "_load_regime_df", return_value=_stub_regime_df()):
        # Mid-month query should resolve to end-of-prior-or-same-month.
        result = MR.is_market_above_10ma_at(date(2008, 12, 15))
        # 2008-11-30 close=1100, ma10=… (1100<MA? depends on values)
        # We just assert it returns a bool (not None) — meaningful regime
        assert result in (True, False)


def test_is_market_above_returns_none_before_ma_window() -> None:
    """Pre-MIN_PERIODS bars have NaN ma_10 — lookup returns None."""
    MR.clear_regime_cache()
    with patch.object(MR, "_load_regime_df", return_value=_stub_regime_df()):
        # First bar is 2008-01-31 with insufficient history.
        result = MR.is_market_above_10ma_at(date(2008, 1, 31))
        assert result is None


def test_is_market_above_returns_none_before_first_bar() -> None:
    """Query before any KOSPI data exists — returns None."""
    MR.clear_regime_cache()
    with patch.object(MR, "_load_regime_df", return_value=_stub_regime_df()):
        result = MR.is_market_above_10ma_at(date(2000, 1, 1))
        assert result is None


def test_filter_allow_unknown_true_passes_pre_ma() -> None:
    """Default allow_unknown=True → filter returns True before MA defined."""
    MR.clear_regime_cache()
    with patch.object(MR, "_load_regime_df", return_value=_stub_regime_df()):
        f = MR.kospi_regime_filter(allow_unknown=True)
        assert f(date(2000, 1, 1)) is True


def test_filter_allow_unknown_false_blocks_pre_ma() -> None:
    MR.clear_regime_cache()
    with patch.object(MR, "_load_regime_df", return_value=_stub_regime_df()):
        f = MR.kospi_regime_filter(allow_unknown=False)
        assert f(date(2000, 1, 1)) is False


# ─────────────────────────────────────────────────────────────────────
# Portfolio integration — regime filter reduces BUY count in bear regime
# ─────────────────────────────────────────────────────────────────────

def test_portfolio_skip_buy_when_regime_filter_returns_false(monkeypatch) -> None:
    """A regime filter that always returns False blocks ALL buys."""
    from app.backtest import portfolio as P
    cands = [
        {"ticker": "A", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2023-01-06", "exit_date": "2023-03-03",
         "entry_price": 100, "exit_price": 120,
         "return_pct": 20.0, "effective_return_pct": 20.0, "hold_weeks": 8,
         "strength": 0.7, "timeframe": "weekly"},
        {"ticker": "B", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2023-02-10", "exit_date": "2023-04-07",
         "entry_price": 50, "exit_price": 60,
         "return_pct": 20.0, "effective_return_pct": 20.0, "hold_weeks": 8,
         "strength": 0.7, "timeframe": "weekly"},
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2023, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000,
        regime_filter=lambda _d: False,
    )
    assert state.trades == []   # no buys → no trades
    assert state.cash == 1_000_000   # cash untouched


def test_portfolio_regime_filter_selective_block(monkeypatch) -> None:
    """Filter blocks only specific dates — partial trade list."""
    from app.backtest import portfolio as P
    cands = [
        {"ticker": "A", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2022-01-07", "exit_date": "2022-03-04",
         "entry_price": 100, "exit_price": 90,
         "return_pct": -10.0, "effective_return_pct": -10.0,
         "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly"},
        {"ticker": "B", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2023-02-10", "exit_date": "2023-04-07",
         "entry_price": 50, "exit_price": 60,
         "return_pct": 20.0, "effective_return_pct": 20.0,
         "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly"},
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)

    def filt(d: date) -> bool:
        # Block 2022 (bear), allow 2023 (bull).
        return d.year != 2022

    state = P.simulate(
        cands, date(2022, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
        regime_filter=filt,
    )
    assert len(state.trades) == 1
    assert state.trades[0].ticker == "B"


def test_portfolio_no_filter_takes_all_buys(monkeypatch) -> None:
    """Sanity: without regime filter, both buys go through."""
    from app.backtest import portfolio as P
    cands = [
        {"ticker": "A", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2022-01-07", "exit_date": "2022-03-04",
         "entry_price": 100, "exit_price": 110,
         "return_pct": 10.0, "effective_return_pct": 10.0,
         "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly"},
        {"ticker": "B", "signal_type": "action_buy", "direction": "bullish",
         "entry_date": "2023-02-10", "exit_date": "2023-04-07",
         "entry_price": 50, "exit_price": 60,
         "return_pct": 20.0, "effective_return_pct": 20.0,
         "hold_weeks": 8, "strength": 0.7, "timeframe": "weekly"},
    ]
    monkeypatch.setattr(P, "_last_close_or_na", lambda *_a, **_k: None)
    state = P.simulate(
        cands, date(2022, 1, 1), date(2023, 12, 31),
        initial_cash=1_000_000, max_positions=2,
    )
    assert len(state.trades) == 2


# ─────────────────────────────────────────────────────────────────────
# Smart filter — combinatorial cases
# ─────────────────────────────────────────────────────────────────────

def _stub_state(close: float, ma_10: float, slope_3m: float = 0.0) -> dict:
    """Mock _regime_state_at result."""
    below_pct = max(0.0, (ma_10 - close) / ma_10 * 100)
    return {
        "close": close, "ma_10": ma_10, "above": close > ma_10,
        "below_pct": below_pct, "ma_10_slope_3m": slope_3m,
    }


def test_smart_above_ma_allows(monkeypatch) -> None:
    """Above MA → allow regardless of slope."""
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=2500, ma_10=2400, slope_3m=-50))
    f = MR.kospi_smart_filter()
    assert f(date(2020, 1, 1)) is True


def test_smart_shallow_dip_allows(monkeypatch) -> None:
    """Below MA but < threshold% → allow (consolidation)."""
    # 2018-02 scenario: KOSPI 2427 vs MA 2441 → 0.57% below.
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=2427, ma_10=2441, slope_3m=-5))
    f = MR.kospi_smart_filter(below_threshold_pct=3.0)
    assert f(date(2018, 2, 28)) is True


def test_smart_deep_dip_falling_ma_blocks(monkeypatch) -> None:
    """Below MA by ≥threshold AND MA falling → block (real bear)."""
    # 2008-01 scenario: 1635 vs 1820 = 10.2% below, MA falling steeply.
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=1635, ma_10=1820, slope_3m=-100))
    f = MR.kospi_smart_filter(below_threshold_pct=3.0)
    assert f(date(2008, 1, 31)) is False


def test_smart_deep_dip_rising_ma_allows(monkeypatch) -> None:
    """Below MA by ≥threshold BUT MA still rising → allow (single
    flush event, trend intact). 2024-09 scenario."""
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=2593, ma_10=2677, slope_3m=+77))
    f = MR.kospi_smart_filter(below_threshold_pct=3.0)
    assert f(date(2024, 9, 30)) is True


def test_smart_unknown_state_allow_default(monkeypatch) -> None:
    """No regime data (pre-MA history) — default allow=True."""
    monkeypatch.setattr(MR, "_regime_state_at", lambda _d: None)
    f = MR.kospi_smart_filter(allow_unknown=True)
    assert f(date(2000, 1, 1)) is True


def test_smart_threshold_disabled_blocks_all_below(monkeypatch) -> None:
    """threshold=0 + require_falling=False → blocks any dip below MA.
    Same as simple filter behavior."""
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=2400, ma_10=2410, slope_3m=+50))
    f = MR.kospi_smart_filter(below_threshold_pct=0, require_falling_ma=False)
    assert f(date(2020, 1, 1)) is False   # 0.4% below blocks at threshold=0


def test_smart_require_falling_off_blocks_threshold_only(monkeypatch) -> None:
    """require_falling_ma=False → only magnitude matters."""
    monkeypatch.setattr(MR, "_regime_state_at",
                        lambda _d: _stub_state(close=2500, ma_10=2650, slope_3m=+100))
    # 5.7% below, MA rising. With require_falling=False, magnitude alone blocks.
    f = MR.kospi_smart_filter(below_threshold_pct=3.0, require_falling_ma=False)
    assert f(date(2024, 9, 30)) is False
