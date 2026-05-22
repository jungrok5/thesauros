"""Synthetic-data unit tests for monthly_10ma_strategy.

These pin down the crossover edge cases that are hard to read off
real Samsung data: prev==MA tie-breaking, single-bar histories,
open positions, window overlap rules.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtest.book_cases.monthly_10ma_strategy import (
    Trade, backtest_10ma, summarize,
)


def _mk(closes: list[float], start: str = "2020-01-31") -> pd.DataFrame:
    """Build a minimal monthly df with the given close series.
    `date` is monthly anchor, other cols mirror close so the strategy
    only ever looks at `close`."""
    dates = pd.date_range(start=start, periods=len(closes), freq="ME")
    df = pd.DataFrame({
        "date": dates,
        "open": closes, "high": closes, "low": closes,
        "close": closes, "adj_close": closes, "volume": 0,
    })
    return df


# ─────────────────────────────────────────────────────────────────────
# Crossover semantics — entry on cross-up, exit on cross-down
# ─────────────────────────────────────────────────────────────────────

def test_single_clean_round_trip() -> None:
    """Build a series that goes clearly below MA → clearly above →
    clearly below. Expect exactly one closed trade.

    Setup: 20 flat bars at 100, then dip to 80 for 5, then rocket to
    150 for 5 (cross up), then crash to 60 for 5 (cross down).
    """
    closes = (
        [100.0] * 20 +
        [80.0] * 5 +
        [150.0] * 5 +
        [60.0] * 5
    )
    df = _mk(closes)
    trades = backtest_10ma(df)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_date is not None
    assert t.entry_price == 150.0
    assert t.exit_price == 60.0
    assert t.return_pct == pytest.approx(-60.0, abs=0.5)


def test_open_position_at_end_of_series() -> None:
    """If the last bar leaves price above MA, the position is OPEN —
    exit_date / exit_price / return_pct must be None."""
    closes = [100.0] * 15 + [150.0] * 10  # cross-up, stays above
    df = _mk(closes)
    trades = backtest_10ma(df)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_date is None
    assert t.exit_price is None
    assert t.return_pct is None


def test_insufficient_bars_returns_empty() -> None:
    """With fewer than the MA window bars, no MA → no trades."""
    df = _mk([100.0] * 5)   # < 10 bars
    assert backtest_10ma(df) == []


# ─────────────────────────────────────────────────────────────────────
# Window overlap — pre-window entry, exit-during-window counted
# ─────────────────────────────────────────────────────────────────────

def test_pre_window_entry_overlapping_window_is_counted() -> None:
    """A trade entered before `start` but exiting inside the window
    must be returned. This is the load-bearing fix that took the
    Samsung case from "3 trades" to the book's "4 trades"."""
    closes = (
        [100.0] * 15 +     # MA warmup
        [120.0] * 5 +      # cross up (pre-window)
        [60.0] * 8         # cross down (inside window); stays below
    )
    df = _mk(closes, start="2020-01-31")
    # Window starts AFTER the entry but contains the exit.
    win_start = date(2021, 7, 1)
    win_end = date(2022, 12, 31)
    trades = backtest_10ma(df, start=win_start, end=win_end)
    assert len(trades) == 1, (
        f"expected exactly 1 overlap-counted trade, got {len(trades)}: "
        f"{[(t.entry_date, t.exit_date) for t in trades]}"
    )
    t = trades[0]
    assert t.entry_date < win_start
    assert t.exit_date is not None and win_start <= t.exit_date <= win_end


def test_pre_window_trade_fully_before_window_is_excluded() -> None:
    """A trade entirely before `start` (entry AND exit before window)
    must NOT appear. Conversely, anchors the overlap rule."""
    closes = (
        [100.0] * 15 +
        [150.0] * 3 +      # entry
        [60.0] * 3 +       # exit
        [100.0] * 20       # rest of series, well within window
    )
    df = _mk(closes, start="2018-01-31")
    win_start = date(2022, 1, 1)
    trades = backtest_10ma(df, start=win_start)
    # The pre-window short trade is excluded; whatever the trailing
    # series does within the window is what we get.
    for t in trades:
        if t.exit_date:
            assert t.exit_date >= win_start, (
                f"pre-window trade exiting {t.exit_date} leaked into result"
            )


# ─────────────────────────────────────────────────────────────────────
# Summarize math — wins / losses / asymmetry
# ─────────────────────────────────────────────────────────────────────

def test_summarize_open_only() -> None:
    """All-open → n_closed=0, no win_rate / asymmetry computed."""
    s = summarize([Trade(date(2020, 1, 1), 100.0, None, None, None)])
    assert s["n_total"] == 1
    assert s["n_closed"] == 0
    assert "win_rate" not in s


def test_summarize_asymmetry() -> None:
    """avg_win / |avg_loss| computed correctly."""
    trades = [
        Trade(date(2020, 1, 1), 100, date(2020, 6, 1), 130, 30.0),
        Trade(date(2021, 1, 1), 100, date(2021, 3, 1),  95, -5.0),
    ]
    s = summarize(trades)
    assert s["n_closed"] == 2
    assert s["win_rate"] == 0.5
    assert s["asymmetry"] == pytest.approx(6.0)
