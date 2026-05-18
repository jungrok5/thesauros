"""End-to-end analyzer tests — synthetic charts in, structured result out.

These exercise analyze_ticker() over a variety of regimes and pin the
contract for everything downstream (recommendations, telegram alerts,
stock detail page) reads.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.book.analyzer import analyze_ticker


def _frame(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    arr = np.asarray(closes, dtype=float)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="W-FRI"),
        "open": arr * (1 + rng.normal(0, 0.002, n)),
        "high": arr * 1.01,
        "low":  arr * 0.99,
        "close": arr, "adj_close": arr,
        "volume": rng.integers(500_000, 2_000_000, n),
    })


# ─────────────────────────────────────────────────────────────────────
# Shape contract: every analyze_ticker result MUST have these fields
# ─────────────────────────────────────────────────────────────────────

REQUIRED_KEYS = {
    "ticker", "as_of", "last_close", "rows", "action", "book_score",
    "trend", "last_candle", "patterns", "reversals", "volume_case",
    "entry_plan",
}


def test_result_shape_uptrend():
    df = _frame(list(np.linspace(50, 150, 260)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    for k in REQUIRED_KEYS:
        assert k in r, f"missing key: {k}"


def test_result_shape_downtrend():
    df = _frame(list(np.linspace(200, 50, 260)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    for k in REQUIRED_KEYS:
        assert k in r, f"missing key: {k}"


# ─────────────────────────────────────────────────────────────────────
# Action determination logic
# ─────────────────────────────────────────────────────────────────────

def test_uptrend_results_in_bullish_action():
    """A steady uptrend should NEVER produce AVOID/SELL_OR_SHORT."""
    df = _frame(list(np.linspace(50, 200, 300)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert r["action"] not in {"AVOID", "SELL_OR_SHORT"}, (
        f"uptrend gave {r['action']}: {r['trend']['book_reason']}"
    )


def test_long_downtrend_results_in_bearish_action():
    """A multi-year downtrend should NEVER produce STRONG_BUY/BUY."""
    df = _frame(list(np.linspace(200, 30, 300)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert r["action"] not in {"STRONG_BUY", "BUY"}, (
        f"downtrend gave {r['action']}: {r['trend']['book_reason']}"
    )


def test_book_score_within_unit_range():
    """book_score must be between -1 and +1 (sanity bound)."""
    for closes in [
        list(np.linspace(50, 150, 260)),
        list(np.linspace(150, 50, 260)),
        [100.0] * 260,
    ]:
        df = _frame(closes)
        df.attrs["grain"] = "W"
        r = analyze_ticker("TEST", df)
        assert -1.0 <= r["book_score"] <= 1.0, (
            f"book_score out of bounds: {r['book_score']}"
        )


# ─────────────────────────────────────────────────────────────────────
# entry_plan staleness guard (the SK텔레콤 fix)
# ─────────────────────────────────────────────────────────────────────

def test_entry_plan_skips_stale_pattern():
    """A breakout pattern that completed long ago + price has run far
    above entry should NOT be re-surfaced as a fresh entry plan.

    Chart: double-bottom completes early then 200%+ run-up."""
    closes = (
        list(np.linspace(100, 50, 30))   # descend
        + list(np.linspace(50, 75, 15))   # rally to neckline
        + list(np.linspace(75, 51, 15))   # 2nd bottom
        + list(np.linspace(51, 90, 20))   # break neckline (= entry zone)
        + list(np.linspace(90, 250, 200)) # extreme run-up (200%+ above breakout)
    )
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    ep = r["entry_plan"]
    if ep is None:
        return    # no bullish action fired → fine
    last_close = float(df["close"].iloc[-1])
    entry = ep["entry"]
    # The entry should NOT be the breakout level (~80) when price is 250.
    # Either a fresh pattern fired with entry ≈ last_close, or the
    # entry_plan should fall through to the 10MA-trailing variant.
    assert entry >= last_close * 0.7, (
        f"stale-pattern guard regressed: entry {entry:.2f} is "
        f"more than 30% below last_close {last_close:.2f}"
    )


def test_entry_plan_stop_practical_for_runaway():
    """When price has run far above the pattern bottom, stop should
    NOT be the pattern's wide bottom-of-formation (e.g., -50%). The
    trailing 주봉 10MA stop should win for risk management."""
    closes = (
        list(np.linspace(100, 50, 30))
        + list(np.linspace(50, 75, 15))
        + list(np.linspace(75, 51, 15))
        + list(np.linspace(51, 90, 20))
        + list(np.linspace(90, 200, 200))
    )
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    ep = r["entry_plan"]
    if ep is None:
        return
    last_close = float(df["close"].iloc[-1])
    # stop must not be more than 30% below current price
    assert ep["stop"] >= last_close * 0.70, (
        f"stop {ep['stop']:.2f} > 30% below last_close {last_close:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────
# Pattern array contract
# ─────────────────────────────────────────────────────────────────────

def test_patterns_have_required_fields():
    df = _frame(list(np.linspace(50, 200, 260)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    for p in r["patterns"]:
        for k in ("kind", "direction", "confidence", "completed"):
            assert k in p, f"pattern missing {k}: {p}"
        assert p["direction"] in ("bullish", "bearish", "neutral"), p
        assert 0.0 <= p["confidence"] <= 1.0, p
        # Plan invariant when present
        e, s, t = p.get("entry"), p.get("stop"), p.get("target")
        if e is not None and s is not None and t is not None:
            if p["direction"] == "bullish":
                assert s < e <= t, f"bad bullish plan: {p}"
            elif p["direction"] == "bearish":
                assert t <= e < s, f"bad bearish plan: {p}"


# ─────────────────────────────────────────────────────────────────────
# Idempotency / determinism
# ─────────────────────────────────────────────────────────────────────

def test_analyze_idempotent_on_identical_input():
    """Same input → same output. No hidden randomness in analyzer."""
    df = _frame(list(np.linspace(60, 140, 260)))
    df.attrs["grain"] = "W"
    r1 = analyze_ticker("TEST", df.copy())
    r2 = analyze_ticker("TEST", df.copy())
    assert r1["action"] == r2["action"]
    assert r1["book_score"] == pytest.approx(r2["book_score"])
    assert len(r1["patterns"]) == len(r2["patterns"])
