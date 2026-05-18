"""Catalyst-candle detector regression suite.

The book treats a single +30%+ bullish bar with 3×+ volume after a
prolonged decline as the most actionable reversal signal — IONQ
2026-04-17 was the live case (+63% on 308M after -52% over 12 weeks).
Before this detector existed the analyzer returned 0 patterns for IONQ
and the stock detail page rendered a generic "추세는 유효하나 명확한
진입 신호 부족" HOLD with no anchor.

These tests pin:
  - the IONQ-shape catalyst fires
  - normal volatile bars don't false-fire
  - 4등분선 (25 / 50 / 75) levels match the book's formula
  - direction is bullish, completed=True
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.book.patterns import detect_catalyst_candle


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """rows = [(open, high, low, close, volume), ...]"""
    n = len(rows)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df["adj_close"] = df["close"]
    df.insert(0, "date", pd.date_range("2025-01-01", periods=n, freq="W-FRI"))
    return df


def test_ionq_shape_catalyst_fires():
    """Long decline → single +63% bullish bar with 3.5× volume."""
    rows: list[tuple] = []
    # 20 bars of mild noise around 60
    rng = np.random.default_rng(42)
    for _ in range(20):
        c = 60 + rng.normal(0, 1)
        rows.append((c, c + 0.5, c - 0.5, c, 100_000))
    # 12 bars of decline 60 → 28
    for c in np.linspace(60, 28, 12):
        rows.append((c + 1, c + 1.5, c - 1, c, 90_000))
    # Catalyst bar: open 28.25, close 46.09, vol 308k (3.4× prior)
    rows.append((28.25, 46.69, 27.87, 46.09, 308_000))
    # A couple of follow-up bars
    rows.append((45, 46, 42, 44, 150_000))
    rows.append((44, 50, 43, 49, 180_000))
    df = _frame(rows)

    p = detect_catalyst_candle(df)
    assert p is not None, "catalyst should fire on the IONQ-shape bar"
    assert p.direction == "bullish"
    assert p.completed is True
    assert p.kind == "장대양봉 catalyst"
    # 4등분선 sanity: 25 % is between open and close, body math right
    open_v = p.extra["catalyst_open"]
    close_v = p.extra["catalyst_close"]
    body = close_v - open_v
    assert abs(p.extra["q25"] - (open_v + body * 0.25)) < 0.01
    assert abs(p.extra["q50"] - (open_v + body * 0.50)) < 0.01
    assert abs(p.extra["q75"] - (open_v + body * 0.75)) < 0.01
    assert p.stop == p.extra["q25"], "stop must equal 25% 절대자리"


def test_steady_uptrend_no_catalyst():
    """Smooth +30% climb over 30 bars with normal volume — should NOT
    fire (no prior decline + no single-bar volume surge)."""
    rows = [(c, c * 1.005, c * 0.995, c * 1.01, 100_000)
            for c in np.linspace(50, 65, 35)]
    df = _frame(rows)
    p = detect_catalyst_candle(df)
    assert p is None, "smooth climb should not register as catalyst"


def test_high_volume_but_no_prior_decline_does_not_fire():
    """Sideways then a +12% bullish bar with 4× volume — but the prior
    12 bars were flat (no decline). Should NOT fire."""
    rows = []
    for _ in range(20):
        rows.append((100, 101, 99, 100, 100_000))
    rows.append((100, 113, 99, 112, 400_000))   # high vol but no setup
    df = _frame(rows)
    p = detect_catalyst_candle(df)
    assert p is None, "no prior decline → not a reversal catalyst"


def test_prior_decline_but_normal_volume_does_not_fire():
    """Decline followed by a normal +12% bar without volume surge."""
    rows = [(c, c + 1, c - 1, c, 100_000) for c in np.linspace(60, 30, 12)]
    rows.append((30, 35, 29, 34, 110_000))   # +13% but only 1.1× volume
    df = _frame(rows)
    p = detect_catalyst_candle(df)
    assert p is None, "without ≥2.5× volume surge, not a catalyst"


def test_picks_strongest_catalyst_when_multiple_in_window():
    """Two catalyst-shape bars within lookback. Detector should keep
    the bigger one (higher body% × vol_mult × decline)."""
    rows = []
    # Long base
    for _ in range(20):
        rows.append((50, 51, 49, 50, 100_000))
    # Decline
    for c in np.linspace(50, 35, 12):
        rows.append((c + 0.5, c + 1, c - 0.5, c, 90_000))
    # First catalyst: +25 % body, 3× vol, depth ~30 %
    rows.append((35, 44, 34, 44, 270_000))
    # Continuation
    for _ in range(3):
        rows.append((44, 45, 43, 44, 120_000))
    # Decline again
    for c in np.linspace(44, 32, 6):
        rows.append((c + 0.5, c + 1, c - 0.5, c, 90_000))
    # Second catalyst: bigger — +50 % body, 4× vol
    rows.append((32, 48, 31, 48, 360_000))
    rows.append((48, 50, 47, 49, 150_000))
    df = _frame(rows)

    p = detect_catalyst_candle(df)
    assert p is not None
    # The second catalyst has higher score; it should be picked.
    assert abs(p.extra["catalyst_close"] - 48.0) < 0.5


def test_catalyst_too_old_outside_lookback_misses():
    """A real catalyst >30 bars in the past should NOT fire under
    default lookback=30."""
    rows = []
    for c in np.linspace(60, 28, 12):
        rows.append((c, c + 1, c - 1, c, 90_000))
    rows.append((28.25, 46.69, 27.87, 46.09, 308_000))   # catalyst
    # 40 normal bars after — pushes catalyst out of lookback=30 window
    for _ in range(40):
        rows.append((46, 47, 45, 46, 100_000))
    df = _frame(rows)
    p = detect_catalyst_candle(df, lookback=30)
    assert p is None, "catalyst more than `lookback` bars ago should be ignored"


def test_runup_since_field_present():
    """For UX/sort logic the page wants to know how far price has run
    past the catalyst close."""
    rows = []
    for c in np.linspace(60, 28, 15):
        rows.append((c, c + 1, c - 1, c, 90_000))
    rows.append((28.25, 46.69, 27.87, 46.09, 308_000))
    rows.append((46, 50, 45, 49.31, 200_000))   # +7 % past catalyst
    df = _frame(rows)
    p = detect_catalyst_candle(df)
    assert p is not None
    runup = p.extra["runup_since"]
    assert 5 <= runup <= 10, f"runup_since should reflect +7%, got {runup:.2f}"
