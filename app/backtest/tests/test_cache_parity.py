"""Cache-parity validation: BACKTEST_NO_CACHE=1 must produce bit-
identical fires to the cache-on path.

The analyzer's performance caches (resample_to_period, find_swings_
for_pattern) are pure-function memoizations within one analyze_ticker
call. Any semantic drift between cached/uncached would be a bug.

These tests run a SMALL synthetic-data walk through walk_ticker_
collect_fires twice — once with caches enabled, once with them
disabled — and assert exact equality of fire records.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


def _synthetic_weekly_bars(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """Deterministic weekly bars long enough for 240MA + patterns."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start="2020-01-03", periods=n, freq="W-FRI")
    # Mix of trend + noise — enough variation to fire diverse signals.
    drift = 1.002
    closes = [50_000.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * drift * (1 + rng.normal(0, 0.025)))
    closes = np.asarray(closes)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.02, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.02, n))
    df = pd.DataFrame({
        "date": dates,
        "open": opens, "high": highs, "low": lows,
        "close": closes, "adj_close": closes,
        "volume": rng.integers(500_000, 5_000_000, n),
    })
    df.attrs["grain"] = "W"
    return df


def _walk_with_cache_mode(disabled: bool, monkeypatch) -> List[Dict[str, Any]]:
    """Run walk_ticker_collect_fires with the BACKTEST_NO_CACHE flag."""
    from app.backtest import sweep as SW
    bars = _synthetic_weekly_bars()
    monkeypatch.setattr(SW, "load_weekly_bars", lambda _t: bars)
    if disabled:
        monkeypatch.setenv("BACKTEST_NO_CACHE", "1")
    else:
        monkeypatch.delenv("BACKTEST_NO_CACHE", raising=False)
    fires = SW.walk_ticker_collect_fires("SYN.KS", 8)
    return fires


# ─────────────────────────────────────────────────────────────────────
# Bit-identical parity — synthetic data
# ─────────────────────────────────────────────────────────────────────

def test_cache_on_vs_off_synthetic_identical(monkeypatch) -> None:
    """The two paths MUST return the same number of fires, same fire
    records, in the same order. If this drifts, the cache is mutating
    semantics — bug."""
    fires_cached = _walk_with_cache_mode(disabled=False, monkeypatch=monkeypatch)
    fires_no_cache = _walk_with_cache_mode(disabled=True, monkeypatch=monkeypatch)
    assert len(fires_cached) == len(fires_no_cache), (
        f"fire count differs: cached={len(fires_cached)} "
        f"vs no_cache={len(fires_no_cache)}"
    )
    for i, (a, b) in enumerate(zip(fires_cached, fires_no_cache)):
        # Compare every field; signal_type / direction / dates / prices
        # / returns must match bit-for-bit. (effective_return is a
        # function of direction + raw return, so derived field too.)
        diffs = {
            k: (a[k], b[k]) for k in a
            if a[k] != b[k]
        }
        if diffs:
            pytest.fail(
                f"fire #{i} differs:\n"
                f"  cached:   {a}\n"
                f"  no_cache: {b}\n"
                f"  diffs:    {diffs}"
            )


def test_cache_on_runs_are_deterministic(monkeypatch) -> None:
    """Within a process, two consecutive cache-ON walks of the same
    synthetic data must give identical results. Catches id(df) reuse
    leaks — the bug we hit before clear_*_cache() was added at the
    start of analyze_ticker."""
    monkeypatch.delenv("BACKTEST_NO_CACHE", raising=False)
    run1 = _walk_with_cache_mode(disabled=False, monkeypatch=monkeypatch)
    run2 = _walk_with_cache_mode(disabled=False, monkeypatch=monkeypatch)
    assert len(run1) == len(run2)
    for a, b in zip(run1, run2):
        for k in a:
            assert a[k] == b[k], (
                f"non-deterministic field {k}: {a[k]} != {b[k]}"
            )


def test_multiple_synthetic_seeds_parity(monkeypatch) -> None:
    """Run parity check across several synthetic seeds. Different
    seeds exercise different swing/pattern paths; we should still
    have cache-on == cache-off for each."""
    from app.backtest import sweep as SW
    for seed in [1, 7, 42, 100]:
        bars = _synthetic_weekly_bars(seed=seed)
        monkeypatch.setattr(SW, "load_weekly_bars", lambda _t, _b=bars: _b)
        monkeypatch.setenv("BACKTEST_NO_CACHE", "1")
        fires_off = SW.walk_ticker_collect_fires("SYN.KS", 8)
        monkeypatch.delenv("BACKTEST_NO_CACHE", raising=False)
        fires_on = SW.walk_ticker_collect_fires("SYN.KS", 8)
        assert len(fires_on) == len(fires_off), (
            f"seed={seed}: count differs cached={len(fires_on)} "
            f"vs no_cache={len(fires_off)}"
        )
        for i, (a, b) in enumerate(zip(fires_on, fires_off)):
            assert a == b, f"seed={seed} fire #{i}: {a} != {b}"


# ─────────────────────────────────────────────────────────────────────
# Same parity check via Kakao 2019-2021 fixture (real OHLCV data)
# ─────────────────────────────────────────────────────────────────────

def test_kakao_fixture_cache_parity(monkeypatch) -> None:
    """Real-data parity. Uses the Phase 2 Kakao fixture (frozen
    historical bars) so we can also verify the analyzer integration
    end-to-end."""
    from app.backtest.book_cases.walk_forward import (
        fixture_to_weekly_df, load_fixture,
    )
    from app.backtest import sweep as SW
    fx = load_fixture("035720_kakao_2019_2021_double_top")
    bars = fixture_to_weekly_df(fx)
    monkeypatch.setattr(SW, "load_weekly_bars", lambda _t: bars)

    monkeypatch.setenv("BACKTEST_NO_CACHE", "1")
    fires_off = SW.walk_ticker_collect_fires("035720.KS", 8)
    monkeypatch.delenv("BACKTEST_NO_CACHE", raising=False)
    fires_on = SW.walk_ticker_collect_fires("035720.KS", 8)

    assert len(fires_on) == len(fires_off), (
        f"Kakao parity: count differs cached={len(fires_on)} "
        f"vs no_cache={len(fires_off)}"
    )
    for i, (a, b) in enumerate(zip(fires_on, fires_off)):
        assert a == b, f"Kakao fire #{i}: {a} != {b}"
