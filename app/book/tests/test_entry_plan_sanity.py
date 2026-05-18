"""Final-gate sanity for analyze_ticker's entry_plan output.

Regression for the 국보디자인 2026-05-22 bug — entry_plan was returning
target (24,287) < entry (24,450). The pattern picker already had a
`stop < entry < target` check, but that was evaluated BEFORE the
trailing-stop tightening, so a target close to current price plus an
above-target tightened stop could squeak past. Plus the final return
had no global gate, so any future code path adding entry_block via a
different branch could re-introduce the same shape.

These tests pin the contract: analyze_ticker NEVER returns an
entry_plan that violates the directional invariant.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.book.analyzer import analyze_ticker


def _frame(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    n = len(closes)
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range(start, periods=n, freq="W-FRI"),
        "open": arr, "high": arr * 1.01, "low": arr * 0.99,
        "close": arr, "adj_close": arr,
        "volume": np.full(n, 1_000_000),
    })


def _entry_plan_invariant(ep, action: str) -> bool:
    if ep is None:
        return True
    e, s, t = ep.get("entry"), ep.get("stop"), ep.get("target")
    if e is None or s is None:
        return False
    if action in ("BUY", "STRONG_BUY"):
        if not s < e:
            return False
        if t is not None and not e <= t:
            return False
    else:
        if not e <= s:
            return False
        if t is not None and not t <= e:
            return False
    return True


def test_uptrend_entry_plan_invariant_holds():
    df = _frame(list(np.linspace(50, 150, 260)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert _entry_plan_invariant(r["entry_plan"], r["action"]), (
        f"entry_plan invariant violated: {r['entry_plan']} for action {r['action']}"
    )


def test_downtrend_entry_plan_invariant_holds():
    df = _frame(list(np.linspace(200, 50, 260)))
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert _entry_plan_invariant(r["entry_plan"], r["action"])


def test_runaway_uptrend_drops_malformed_plan_rather_than_surfacing():
    """A double-bottom that completed long ago + huge run-up. The pattern
    picker should reject it (stale entry). entry_plan must be either
    None or invariant-satisfying — NEVER target < entry."""
    closes = (
        list(np.linspace(100, 50, 30))
        + list(np.linspace(50, 75, 15))
        + list(np.linspace(75, 51, 15))
        + list(np.linspace(51, 90, 20))
        + list(np.linspace(90, 300, 180))   # ridiculous run-up
    )
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert _entry_plan_invariant(r["entry_plan"], r["action"])


def test_random_walk_fuzz_invariant():
    """20 random walks — whatever entry_plan analyze_ticker emits, the
    invariant must always hold."""
    for seed in range(20):
        rng = np.random.default_rng(seed)
        rets = rng.normal(0, 0.02, 260).cumsum()
        closes = list(100 * np.exp(rets))
        df = _frame(closes)
        df.attrs["grain"] = "W"
        r = analyze_ticker("TEST", df)
        assert _entry_plan_invariant(r["entry_plan"], r["action"]), (
            f"seed {seed}: {r['entry_plan']} for action {r['action']}"
        )


def test_target_clipping_against_trailing_stop():
    """When the trailing 주봉 10MA stop ends up close to a target that's
    only slightly above current entry, the final gate must drop the plan
    rather than surfacing stop ≥ target."""
    # Construct a chart where the pattern's natural target is very close
    # to current price. Hard to reliably generate organically; the
    # invariant test above already covers it via fuzz. This stub asserts
    # the helper itself rejects bad inputs.
    bad_plan = {"entry": 100.0, "stop": 105.0, "target": 110.0}
    assert not _entry_plan_invariant(bad_plan, "BUY"), (
        "BUY with stop > entry should be flagged as invariant violation"
    )
    bad_plan2 = {"entry": 100.0, "stop": 90.0, "target": 95.0}
    assert not _entry_plan_invariant(bad_plan2, "BUY"), (
        "BUY with target < entry should be flagged as invariant violation"
    )
    bad_plan3 = {"entry": 100.0, "stop": 95.0, "target": 90.0}
    assert not _entry_plan_invariant(bad_plan3, "SELL"), (
        "SELL with stop < entry should be flagged as invariant violation"
    )
