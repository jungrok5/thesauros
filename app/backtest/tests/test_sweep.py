"""Unit tests for app.backtest.sweep.

Coverage:
  - signal_direction: bullish / bearish / neutral inference
  - effective_return: direction-aware inversion
  - aggregate_by_signal: math (win_rate, payoff, best_ticker)
  - aggregate_top_per_signal: top-N selection by effective return
  - walk_ticker_collect_fires: mocked-DB integration (PIT safety
    inherited from single_signal)
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.backtest import sweep


# ─────────────────────────────────────────────────────────────────────
# Direction inference
# ─────────────────────────────────────────────────────────────────────

def test_direction_bullish_action() -> None:
    assert sweep.signal_direction("action_buy") == "bullish"
    assert sweep.signal_direction("action_strong_buy") == "bullish"


def test_direction_bearish_action() -> None:
    assert sweep.signal_direction("action_sell") == "bearish"
    assert sweep.signal_direction("action_sell_short") == "bearish"
    assert sweep.signal_direction("action_avoid") == "bearish"


def test_direction_pattern_bearish_suffix() -> None:
    """pattern_double_top / triple_top / head_and_shoulders → bearish."""
    assert sweep.signal_direction("pattern_double_top") == "bearish"
    assert sweep.signal_direction("pattern_triple_top") == "bearish"
    assert sweep.signal_direction("pattern_head_and_shoulders") == "bearish"
    assert sweep.signal_direction("pattern_death_messenger") == "bearish"
    assert sweep.signal_direction("pattern_rounding_top") == "bearish"


def test_direction_pattern_default_bullish() -> None:
    """pattern_* without a known bearish suffix → bullish (the
    majority case — most pattern detectors are buy signals)."""
    assert sweep.signal_direction("pattern_double_bottom") == "bullish"
    assert sweep.signal_direction("pattern_triple_bottom") == "bullish"
    assert sweep.signal_direction("pattern_ma240_breakout") == "bullish"
    assert sweep.signal_direction("pattern_inverse_head_and_shoulders") == "bullish"


def test_direction_params_overrides_inference() -> None:
    """When params['direction'] is explicit, it wins over signal_type
    inference. Critical for volume_case_X (signal_type doesn't encode
    direction; only params does)."""
    assert sweep.signal_direction("volume_case_4", "bearish") == "bearish"
    assert sweep.signal_direction("volume_case_3", "bullish") == "bullish"
    # Even override action_buy if params says otherwise (defensive).
    assert sweep.signal_direction("action_buy", "neutral") == "neutral"


def test_direction_unknown_signal_type() -> None:
    assert sweep.signal_direction("unknown_xyz") == "neutral"


# ─────────────────────────────────────────────────────────────────────
# Effective return — bearish inversion
# ─────────────────────────────────────────────────────────────────────

def test_effective_return_bullish_unchanged() -> None:
    assert sweep.effective_return(10.0, "bullish") == 10.0
    assert sweep.effective_return(-5.0, "bullish") == -5.0


def test_effective_return_bearish_inverted() -> None:
    """For a bearish (sell/short) signal, +10% raw return is BAD
    (price went up despite sell signal) → effective -10%."""
    assert sweep.effective_return(10.0, "bearish") == -10.0
    assert sweep.effective_return(-5.0, "bearish") == 5.0


def test_effective_return_neutral_unchanged() -> None:
    assert sweep.effective_return(3.0, "neutral") == 3.0


# ─────────────────────────────────────────────────────────────────────
# Aggregation
# ─────────────────────────────────────────────────────────────────────

def _mkfire(ticker: str, sig: str, ret: float,
            direction: str = "bullish") -> dict:
    return {
        "ticker": ticker,
        "signal_type": sig,
        "direction": direction,
        "return_pct": ret,
        "effective_return_pct": sweep.effective_return(ret, direction),
        "entry_date": "2024-01-05",
        "hold_weeks": 8,
    }


def test_aggregate_basic_math() -> None:
    """5 fires of one signal: 3 wins (+10/+20/+30) and 2 losses
    (-5/-5). win_rate=60%, avg=10%, payoff = 20/5 = 4.0."""
    fires = [
        _mkfire("A", "pattern_double_bottom", 10),
        _mkfire("B", "pattern_double_bottom", 20),
        _mkfire("C", "pattern_double_bottom", 30),
        _mkfire("D", "pattern_double_bottom", -5),
        _mkfire("E", "pattern_double_bottom", -5),
    ]
    rows = sweep.aggregate_by_signal(fires)
    assert len(rows) == 1
    r = rows[0]
    assert r["n_fires"] == 5
    assert r["n_tickers"] == 5
    assert r["win_rate"] == pytest.approx(0.6)
    assert r["avg_return_pct"] == pytest.approx(10.0)
    assert r["payoff"] == pytest.approx(4.0)
    assert r["best_ticker"] == "C"   # +30 best
    assert r["best_pct"] == pytest.approx(30.0)


def test_aggregate_bearish_uses_effective_return() -> None:
    """Bearish signal: raw returns +5, -10 → effective -5, +10. So
    win_rate = 1/2 = 50%, best = +10 (the price-dropped fire)."""
    fires = [
        _mkfire("X", "pattern_double_top", 5, direction="bearish"),
        _mkfire("Y", "pattern_double_top", -10, direction="bearish"),
    ]
    rows = sweep.aggregate_by_signal(fires)
    r = rows[0]
    assert r["direction"] == "bearish"
    assert r["win_rate"] == pytest.approx(0.5)
    # best_pct is the highest EFFECTIVE return — the bear signal that
    # correctly predicted a drop.
    assert r["best_pct"] == pytest.approx(10.0)
    assert r["best_ticker"] == "Y"


def test_aggregate_no_losses_payoff_is_none() -> None:
    """All-wins → payoff is undefined (can't divide by avg-loss=0)."""
    fires = [
        _mkfire("A", "x", 5), _mkfire("B", "x", 10),
    ]
    rows = sweep.aggregate_by_signal(fires)
    assert rows[0]["payoff"] is None


def test_aggregate_sort_by_n_fires() -> None:
    fires = (
        [_mkfire("A", "few", 5)]
        + [_mkfire(f"T{i}", "many", i) for i in range(1, 11)]
    )
    rows = sweep.aggregate_by_signal(fires)
    assert rows[0]["signal_type"] == "many"
    assert rows[1]["signal_type"] == "few"


# ─────────────────────────────────────────────────────────────────────
# Top-per-signal
# ─────────────────────────────────────────────────────────────────────

def test_top_per_signal_orders_by_effective_return() -> None:
    fires = [
        _mkfire("A", "pattern_double_top", 5, direction="bearish"),    # eff -5
        _mkfire("B", "pattern_double_top", -20, direction="bearish"),  # eff +20
        _mkfire("C", "pattern_double_top", -10, direction="bearish"),  # eff +10
    ]
    top = sweep.aggregate_top_per_signal(fires, top_n=3)
    seq = [f["ticker"] for f in top["pattern_double_top"]]
    assert seq == ["B", "C", "A"]


# ─────────────────────────────────────────────────────────────────────
# walk_ticker_collect_fires — integration with mocked DB / analyzer
# ─────────────────────────────────────────────────────────────────────

def _synthetic_bars(n: int = 120, start: str = "2022-01-07") -> pd.DataFrame:
    """Smooth uptrend weekly bars."""
    rng = np.random.default_rng(seed=7)
    dates = pd.date_range(start=start, periods=n, freq="W-FRI")
    closes = 100.0 * (1.003 ** np.arange(n))
    closes *= (1 + rng.normal(0, 0.01, n))
    df = pd.DataFrame({
        "date": dates,
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "adj_close": closes, "volume": 1_000_000,
    })
    df.attrs["grain"] = "W"
    return df


def test_walk_returns_empty_when_no_bars() -> None:
    with patch.object(sweep, "load_weekly_bars",
                      return_value=pd.DataFrame()):
        assert sweep.walk_ticker_collect_fires("EMPTY", 8) == []


def test_walk_returns_empty_when_short_history() -> None:
    df = _synthetic_bars(40)   # < _MIN_BARS + hold_weeks
    with patch.object(sweep, "load_weekly_bars", return_value=df):
        assert sweep.walk_ticker_collect_fires("SHORT", 8) == []


def test_walk_records_fire_per_signal_at_each_bar() -> None:
    """If analyze fires 2 signals at one bar, we get 2 fire records
    for that bar — one per signal."""
    df = _synthetic_bars(120)
    fire_idx = 60

    def fake_analyze(_t, pit, **_kw):
        if len(pit) - 1 == fire_idx:
            return {"_fire": True}
        return {}

    def fake_extract(result):
        if not result.get("_fire"):
            return []
        return [
            {"signal_type": "pattern_double_bottom", "timeframe": "weekly",
             "strength": 0.85, "params": {"direction": "bullish"}},
            {"signal_type": "pattern_double_top", "timeframe": "weekly",
             "strength": 0.75, "params": {"direction": "bearish"}},
        ]

    with patch.object(sweep, "load_weekly_bars", return_value=df), \
         patch.object(sweep, "analyze_ticker", side_effect=fake_analyze), \
         patch.object(sweep, "extract_signals", side_effect=fake_extract):
        fires = sweep.walk_ticker_collect_fires("TKR", hold_weeks=4)

    assert len(fires) == 2
    types = {f["signal_type"] for f in fires}
    assert types == {"pattern_double_bottom", "pattern_double_top"}
    # Both share entry/exit dates, opposite directions, opposite eff return signs.
    f_long = next(f for f in fires if f["direction"] == "bullish")
    f_short = next(f for f in fires if f["direction"] == "bearish")
    assert f_long["entry_date"] == f_short["entry_date"]
    assert f_long["effective_return_pct"] == pytest.approx(
        -f_short["effective_return_pct"]
    )


def test_walk_skips_bar_when_analyze_raises() -> None:
    """A single analyzer exception should NOT abort the ticker —
    other bars continue to be processed."""
    df = _synthetic_bars(120)
    raise_idx = 70

    def fake_analyze(_t, pit, **_kw):
        if len(pit) - 1 == raise_idx:
            raise RuntimeError("synthetic analyze fail")
        return {}

    with patch.object(sweep, "load_weekly_bars", return_value=df), \
         patch.object(sweep, "analyze_ticker", side_effect=fake_analyze), \
         patch.object(sweep, "extract_signals", return_value=[]):
        fires = sweep.walk_ticker_collect_fires("TKR", hold_weeks=4)

    assert fires == []   # no signals fired in this fake, but walker survived
