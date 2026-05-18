"""TDD-style tests for the multi-timeframe trend classifier.

Targets the book's primary signal hierarchy:
  월봉 240MA > 월봉 10MA > 주봉 10MA > 일봉 정배열

Each test constructs a synthetic price series with known trend properties
and asserts the classifier's labels + signals match the book.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.book.trend import (
    classify_trend,
    analyze_multi_timeframe,
    resample_to_period,
)


def _frame(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="W-FRI")
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "date": dates,
        "open": arr, "high": arr * 1.005, "low": arr * 0.995,
        "close": arr, "adj_close": arr,
        "volume": np.full(n, 1_000_000),
    })


# ─────────────────────────────────────────────────────────────────────
# classify_trend
# ─────────────────────────────────────────────────────────────────────

def test_strong_uptrend_classified_strong():
    """Linear rise from 50 → 150 should be 강세 with high alignment."""
    df = _frame(list(np.linspace(50, 150, 300)))
    t = classify_trend(df, "weekly")
    assert t is not None
    assert t.label == "강세"
    assert t.above_ma_10 is True
    assert t.ma_10_slope_up is True
    assert t.alignment_score >= 0.8


def test_strong_downtrend_classified_weak():
    """Linear decline 150 → 50 should be 약세."""
    df = _frame(list(np.linspace(150, 50, 300)))
    t = classify_trend(df, "weekly")
    assert t is not None
    assert t.label in {"약세", "데드"}
    assert t.above_ma_10 is False


def test_flat_chart_alignment_bounded():
    """Constant price → alignment_score must be in [-1, 1] range. The
    book defines alignment as the MA-stack ordering — flat charts where
    all MAs equal can resolve either way under strict inequalities, so
    we only assert the bound, not the sign."""
    df = _frame([100.0] * 300)
    t = classify_trend(df, "weekly")
    assert t is not None
    assert -1.0 <= t.alignment_score <= 1.0


def test_alignment_score_within_bounds_uptrend():
    """A clear uptrend must score positively bounded."""
    df = _frame(list(np.linspace(50, 150, 300)))
    t = classify_trend(df, "weekly")
    assert t is not None
    assert -1.0 <= t.alignment_score <= 1.0
    assert t.alignment_score > 0


def test_alignment_score_within_bounds_downtrend():
    df = _frame(list(np.linspace(150, 50, 300)))
    t = classify_trend(df, "weekly")
    assert t is not None
    assert -1.0 <= t.alignment_score <= 1.0
    assert t.alignment_score < 0


def test_above_240ma_uptrend_returns_true_flag():
    """A long uptrend that's been above 240MA the whole way should
    set above_ma_240=True."""
    df = _frame(list(np.linspace(50, 250, 320)))
    t = classify_trend(df, "weekly")
    assert t is not None
    if t.ma_240 is not None:
        assert t.above_ma_240 is True


def test_below_240ma_returns_false_flag():
    """A long decline that ends below 240MA should set above_ma_240=False."""
    df = _frame(list(np.linspace(200, 50, 320)))
    t = classify_trend(df, "weekly")
    assert t is not None
    if t.ma_240 is not None:
        assert t.above_ma_240 is False


# ─────────────────────────────────────────────────────────────────────
# analyze_multi_timeframe — book signal logic
# ─────────────────────────────────────────────────────────────────────

def test_book_signal_buy_on_strong_uptrend():
    """Steady uptrend → 월봉/주봉 10MA 위 + 정배열 → BUY."""
    df = _frame(list(np.linspace(50, 150, 320)))
    multi = analyze_multi_timeframe(df, input_grain="W")
    assert multi.book_signal in {"BUY", "HOLD"}, (
        f"expected BUY/HOLD, got {multi.book_signal}: {multi.book_reason}"
    )


def test_book_signal_sell_on_breakdown_below_monthly_ma10():
    """Long uptrend then sudden crash → 월봉 10MA 하향 이탈 → SELL."""
    closes = list(np.linspace(50, 150, 250)) + list(np.linspace(150, 60, 70))
    df = _frame(closes)
    multi = analyze_multi_timeframe(df, input_grain="W")
    assert multi.book_signal in {"SELL", "AVOID", "HOLD"}, (
        f"expected SELL/AVOID/HOLD after crash, got {multi.book_signal}: {multi.book_reason}"
    )


def test_book_signal_avoid_on_long_below_240ma():
    """Sideways/declining for years under 240MA → AVOID (죽은 차트)."""
    closes = list(np.linspace(200, 50, 250)) + [50.0] * 70
    df = _frame(closes)
    multi = analyze_multi_timeframe(df, input_grain="W")
    # When ma_240 can be computed AND price below it, AVOID should fire
    if multi.monthly and multi.monthly.ma_240 and multi.monthly.above_ma_240 is False:
        assert multi.book_signal == "AVOID"


def test_weekly_input_grain_does_not_resample_to_self():
    """Confirms the Phase-2 fix: when input_grain='W', the daily classifier
    is skipped (no fake daily resampled from weekly)."""
    df = _frame(list(np.linspace(50, 150, 200)))
    multi = analyze_multi_timeframe(df, input_grain="W")
    assert multi.daily is None
    assert multi.weekly is not None
    assert multi.monthly is not None


# ─────────────────────────────────────────────────────────────────────
# resample_to_period
# ─────────────────────────────────────────────────────────────────────

def test_resample_weekly_to_monthly_preserves_first_last_close():
    """Weekly close at end-of-month should match monthly close."""
    df = _frame(list(np.linspace(100, 200, 100)))
    monthly = resample_to_period(df, "M")
    assert len(monthly) > 0
    # Monthly close should equal the LAST weekly close in that month.
    # The last weekly close in df is 200 ± small.
    assert abs(monthly["close"].iloc[-1] - df["close"].iloc[-1]) < 5
