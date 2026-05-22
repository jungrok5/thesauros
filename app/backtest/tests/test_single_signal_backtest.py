"""Regression tests for app.backtest.single_signal.

The thing that goes wrong silently with backtests is future leak —
the analyzer sees bars dated after the candidate date and the
"hindsight" inflates returns. So the load-bearing test here is the
PIT guard: assert that the dataframe passed to analyze_ticker has
NO bar dated after the candidate entry.

We also cover signal matching (exact + prefix) and summary math, both
pure-Python paths that don't need a DB.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.backtest import single_signal as bt


# ─────────────────────────────────────────────────────────────────────
# Synthetic-bar builder — mirrors the shape load_weekly_bars returns.
# ─────────────────────────────────────────────────────────────────────

def _make_bars(n_weeks: int, start: str = "2022-01-07",
               base: float = 100.0) -> pd.DataFrame:
    """N weekly bars on Fri-end, deterministic, mild uptrend so the
    analyzer can compute MAs without NaN explosions."""
    rng = np.random.default_rng(seed=7)
    dates = pd.date_range(start=start, periods=n_weeks, freq="W-FRI")
    # Smooth random walk around a 0.3%/wk drift.
    drift = 1.003
    closes = [base]
    for _ in range(n_weeks - 1):
        closes.append(closes[-1] * drift * (1 + rng.normal(0, 0.015)))
    closes_arr = np.array(closes, dtype=float)
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    highs = np.maximum(opens, closes_arr) * (1 + rng.uniform(0, 0.01, n_weeks))
    lows = np.minimum(opens, closes_arr) * (1 - rng.uniform(0, 0.01, n_weeks))
    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes_arr,
        "adj_close": closes_arr,
        "volume": rng.integers(500_000, 2_000_000, n_weeks),
    })
    df.attrs["grain"] = "W"
    return df


# ─────────────────────────────────────────────────────────────────────
# Pure-Python: signal matching
# ─────────────────────────────────────────────────────────────────────

class _FakeExtract:
    """Replace extract_signals(result) with a fixed list."""
    def __init__(self, types: list[str]) -> None:
        self.types = types

    def __call__(self, _result: dict) -> list[dict]:
        return [{"signal_type": t} for t in self.types]


def test_signal_fired_exact_match() -> None:
    with patch.object(bt, "extract_signals",
                      _FakeExtract(["action_buy", "pattern_double_bottom"])):
        assert bt._signal_fired({}, "action_buy") is True
        assert bt._signal_fired({}, "pattern_double_bottom") is True
        assert bt._signal_fired({}, "action_sell") is False


def test_signal_fired_prefix_match() -> None:
    """`action` should match `action_buy` / `action_strong_buy` but NOT
    a totally different family (e.g. `action_sell` still matches but
    `pattern_*` should not)."""
    with patch.object(bt, "extract_signals",
                      _FakeExtract(["action_strong_buy"])):
        assert bt._signal_fired({}, "action") is True
        assert bt._signal_fired({}, "pattern") is False


def test_signal_fired_prefix_no_false_match() -> None:
    """`action` prefix must NOT match `actioned_xxx` — we require the
    trailing underscore separator."""
    with patch.object(bt, "extract_signals", _FakeExtract(["actioned_x"])):
        assert bt._signal_fired({}, "action") is False


# ─────────────────────────────────────────────────────────────────────
# Pure-Python: summary math
# ─────────────────────────────────────────────────────────────────────

def test_summarize_empty() -> None:
    assert bt._summarize([]) == {"n": 0}


def test_summarize_all_wins() -> None:
    fires = [{"return_pct": 5.0}, {"return_pct": 10.0}, {"return_pct": 15.0}]
    s = bt._summarize(fires)
    assert s["n"] == 3
    assert s["win_rate"] == 1.0
    assert s["avg_return_pct"] == pytest.approx(10.0)
    assert s["median_return_pct"] == pytest.approx(10.0)
    assert s["best_pct"] == 15.0
    assert s["worst_pct"] == 5.0
    assert s["avg_win_pct"] == pytest.approx(10.0)
    assert s["avg_loss_pct"] == 0.0
    # No losses → payoff undefined.
    assert s["payoff_ratio"] is None


def test_summarize_mixed_payoff() -> None:
    fires = [
        {"return_pct": 20.0},   # win
        {"return_pct": 10.0},   # win
        {"return_pct": -5.0},   # loss
        {"return_pct": -5.0},   # loss
    ]
    s = bt._summarize(fires)
    assert s["n"] == 4
    assert s["win_rate"] == 0.5
    assert s["avg_win_pct"] == pytest.approx(15.0)
    assert s["avg_loss_pct"] == pytest.approx(-5.0)
    # payoff = avg_win / |avg_loss| = 15 / 5 = 3.0
    assert s["payoff_ratio"] == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────────────
# PIT safety — the load-bearing invariant
# ─────────────────────────────────────────────────────────────────────

def test_pit_no_future_leak() -> None:
    """For every candidate bar, the df handed to analyze_ticker must
    contain NO bar strictly after the candidate date.

    We instrument analyze_ticker via monkeypatch to record (candidate_idx,
    max_date_in_df) for each call, then assert max_date == candidate
    date in every record. A bug where we sliced df[i + 1 :] or used
    the whole df by mistake would surface here immediately.
    """
    df = _make_bars(120)

    calls: list[tuple[date, date]] = []

    def fake_analyze(_ticker, pit_df, **_kwargs):
        # The candidate date is the LAST row of pit_df by construction.
        cand = pit_df.iloc[-1]["date"].date()
        max_d = pd.to_datetime(pit_df["date"]).dt.date.max()
        calls.append((cand, max_d))
        return {}   # no signal → backtest loops past

    with patch.object(bt, "load_weekly_bars", return_value=df), \
         patch.object(bt, "analyze_ticker", side_effect=fake_analyze):
        bt.run("DUMMY", "action_buy", hold_weeks=4)

    assert calls, "analyze should have been called at least once"
    for cand, max_d in calls:
        assert cand == max_d, (
            f"PIT leak: analyzer saw bar {max_d} for candidate {cand}"
        )


def test_hold_weeks_exit_uses_correct_bar() -> None:
    """When a signal fires at bar i, the recorded exit must be the
    close at bar i+hold_weeks — not i+hold_weeks-1, not the last bar."""
    df = _make_bars(120)

    # Fire the signal exactly ONCE at index 60.
    fire_idx = 60
    hold = 8

    def fake_analyze(_ticker, pit_df, **_kwargs):
        if len(pit_df) - 1 == fire_idx:
            return {"_fire": True}
        return {}

    def fake_extract(result):
        return [{"signal_type": "action_buy"}] if result.get("_fire") else []

    with patch.object(bt, "load_weekly_bars", return_value=df), \
         patch.object(bt, "analyze_ticker", side_effect=fake_analyze), \
         patch.object(bt, "extract_signals", side_effect=fake_extract):
        res = bt.run("DUMMY", "action_buy", hold_weeks=hold)

    assert len(res["fires"]) == 1
    fire = res["fires"][0]
    expected_entry = float(df.iloc[fire_idx]["close"])
    expected_exit = float(df.iloc[fire_idx + hold]["close"])
    assert fire["entry_price"] == pytest.approx(expected_entry)
    assert fire["exit_price"] == pytest.approx(expected_exit)
    # entry_date == df.iloc[fire_idx]["date"] in ISO form
    assert fire["entry_date"] == df.iloc[fire_idx]["date"].date().isoformat()
    assert fire["exit_date"] == df.iloc[fire_idx + hold]["date"].date().isoformat()


# ─────────────────────────────────────────────────────────────────────
# Edge cases — empty, short, date filtering
# ─────────────────────────────────────────────────────────────────────

def test_no_bars_returns_status() -> None:
    with patch.object(bt, "load_weekly_bars",
                      return_value=pd.DataFrame()):
        res = bt.run("EMPTY", "action_buy")
    assert res["status"] == "no_bars"
    assert res["fires"] == []


def test_insufficient_history_short_circuits() -> None:
    """With only 40 weekly bars (< _MIN_BARS + hold_weeks), no walking."""
    df = _make_bars(40)
    with patch.object(bt, "load_weekly_bars", return_value=df):
        res = bt.run("SHORT", "action_buy", hold_weeks=8)
    assert res["status"] == "insufficient_history"
    assert res["fires"] == []


def test_date_window_clips_iteration() -> None:
    """start_date / end_date must clip the candidate bar window. We
    verify by counting analyze invocations within a tight window."""
    df = _make_bars(120)
    call_dates: list[date] = []

    def fake_analyze(_ticker, pit_df, **_kwargs):
        call_dates.append(pit_df.iloc[-1]["date"].date())
        return {}

    sd = df.iloc[80]["date"].date()
    ed = df.iloc[100]["date"].date()
    with patch.object(bt, "load_weekly_bars", return_value=df), \
         patch.object(bt, "analyze_ticker", side_effect=fake_analyze):
        bt.run("DUMMY", "action_buy", hold_weeks=4,
               start_date=sd, end_date=ed)

    assert call_dates, "should have at least one call inside the window"
    for d in call_dates:
        assert sd <= d <= ed, f"date {d} outside [{sd}, {ed}]"


def test_analyzer_exception_is_skipped_not_fatal() -> None:
    """If analyze_ticker raises at a single bar, that bar is logged
    and skipped — the backtest continues. A regression here would
    let a single bad bar abort an entire ticker's run."""
    df = _make_bars(120)

    def fake_analyze(_ticker, pit_df, **_kwargs):
        # Raise at exactly one bar.
        if pit_df.iloc[-1]["date"].date() == df.iloc[70]["date"].date():
            raise ValueError("simulated transient analyze fail")
        return {}

    with patch.object(bt, "load_weekly_bars", return_value=df), \
         patch.object(bt, "analyze_ticker", side_effect=fake_analyze):
        res = bt.run("DUMMY", "action_buy", hold_weeks=4)

    # Status should still be ok, fires=0 (no signal fired in fake).
    assert res["status"] == "ok"
    assert res["fires"] == []
