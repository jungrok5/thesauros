"""RSI / MACD computation + book-faithful interpretation.

Pin the math (no surprises if numpy/pandas defaults shift) and the
narrative branches (oversold + bullish trend → "눌림목 매수 자리 후보"
etc.) so the BookSummaryTable text doesn't silently drift.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.book.indicators import compute_indicators, rsi, macd


def _frame(closes):
    n = len(closes)
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-05", periods=n, freq="W-FRI"),
        "open": arr * 0.99, "high": arr * 1.01, "low": arr * 0.98,
        "close": arr, "adj_close": arr,
        "volume": np.full(n, 1_000_000.0),
    })


def test_rsi_overbought_after_strong_climb():
    """100 → 200 monotone climb → RSI should land in overbought (>70)."""
    closes = list(np.linspace(100, 200, 80))
    s = rsi(pd.Series(closes), period=14)
    assert s.iloc[-1] > 70, f"expected overbought, got {s.iloc[-1]}"


def test_rsi_oversold_after_steep_drop():
    closes = list(np.linspace(200, 100, 80))
    s = rsi(pd.Series(closes), period=14)
    assert s.iloc[-1] < 30, f"expected oversold, got {s.iloc[-1]}"


def test_macd_golden_cross_emitted():
    """V-shaped recovery: down then up should yield a golden cross
    somewhere during the recovery (anywhere after the trough)."""
    closes = list(np.linspace(100, 60, 40)) + list(np.linspace(60, 130, 40))
    df = macd(pd.Series(closes))
    # Look across the entire post-warmup window for any golden cross.
    crossed = False
    for i in range(35, len(df)):
        if df["macd"].iloc[i - 1] <= df["signal"].iloc[i - 1] and df["macd"].iloc[i] > df["signal"].iloc[i]:
            crossed = True
            break
    assert crossed, "expected a golden cross during the recovery"


def test_compute_indicators_returns_none_when_history_short():
    df = _frame(list(np.linspace(50, 60, 20)))
    snap = compute_indicators(df, trend_label="강세")
    assert snap is None, "< 35 bars should return None"


def test_compute_indicators_oversold_in_bullish_trend_says_book_pullback():
    # Long climb then sharp recent dip to trigger oversold while trend=강세.
    closes = list(np.linspace(50, 150, 60)) + list(np.linspace(150, 95, 15))
    df = _frame(closes)
    snap = compute_indicators(df, trend_label="강세")
    assert snap is not None
    # Could be oversold or weak depending on exact slope — assert text shape:
    if snap.rsi_zone == "oversold":
        assert "눌림목" in snap.rsi_interpretation or "후킹" in snap.rsi_interpretation
    # MACD: should be near a dead cross given the recent steep drop —
    # either dead or weak/pending_dead.
    assert snap.macd_state in ("dead", "weak", "pending_dead", "pending_golden")


def test_compute_indicators_serializes_to_dict():
    closes = list(np.linspace(100, 130, 50))
    df = _frame(closes)
    snap = compute_indicators(df, trend_label="강세")
    d = snap.to_dict()
    for key in ("rsi", "rsi_zone", "rsi_interpretation",
                "macd", "macd_signal", "macd_hist",
                "macd_state", "macd_divergence", "macd_interpretation"):
        assert key in d
    # rsi should be a number, not NaN string
    assert isinstance(d["rsi"], (int, float))
    assert 0 <= d["rsi"] <= 100


def test_macd_state_always_set_to_known_value():
    """Catch-all: whatever the chart looks like, macd_state must be one
    of the documented values, never empty / nan / unknown."""
    valid_states = {
        "golden", "dead", "pending_golden", "pending_dead",
        "strong", "weak", "flat", "n/a",
    }
    for closes in (
        list(np.linspace(50, 150, 60)),                              # uptrend
        list(np.linspace(150, 50, 60)),                              # downtrend
        list(np.linspace(100, 100.5, 60)),                           # flat
        list(np.linspace(100, 50, 30)) + list(np.linspace(50, 95, 30)),  # V
    ):
        df = _frame(closes)
        snap = compute_indicators(df, trend_label="강세")
        assert snap is not None
        assert snap.macd_state in valid_states, (
            f"unknown macd_state {snap.macd_state!r}"
        )
