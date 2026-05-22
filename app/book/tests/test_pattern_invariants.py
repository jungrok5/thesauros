"""Pattern-detector invariant tests using synthetic OHLCV data.

These tests catch the family of bugs that surfaced in SK텔레콤 (2026-05-22):
target/stop on wrong side of entry, neckline extrapolated past the head,
stale completed patterns surfaced as fresh entry plans.

Every bullish pattern MUST satisfy:    stop < entry <= target
Every bearish pattern MUST satisfy:    target <= entry < stop

We test each detector against:
  (a) a known-good synthetic chart that should fire the pattern
  (b) random-walk noise charts that should NOT fire spurious bad plans

Run:  python -m pytest app/book/tests/test_pattern_invariants.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.book.patterns import (
    detect_double_bottom,
    detect_double_top,
    detect_head_and_shoulders,
    detect_reverse_head_and_shoulders,
    detect_triple_bottom,
    detect_triple_top,
    detect_cup_and_handle,
    detect_240ma_breakout,
    detect_dolbanji,
    detect_forking,
    detect_all,
)
from app.book.analyzer import analyze_ticker


# ─────────────────────────────────────────────────────────────────────
# Synthetic chart builders
# ─────────────────────────────────────────────────────────────────────

def _to_df(closes: list[float], start_date: str = "2024-01-01") -> pd.DataFrame:
    """Wrap a close-price series into the OHLCV DataFrame shape every
    detector expects. open=prev_close, high/low = small jitter, vol = 1M."""
    rng = np.random.default_rng(seed=42)
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    jitter_h = rng.uniform(0.0, 0.01, n)
    jitter_l = rng.uniform(0.0, 0.01, n)
    highs = np.maximum(opens, closes_arr) * (1 + jitter_h)
    lows = np.minimum(opens, closes_arr) * (1 - jitter_l)
    dates = pd.date_range(start=start_date, periods=n, freq="W-FRI")
    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes_arr,
        "adj_close": closes_arr,
        "volume": rng.integers(500_000, 2_000_000, n),
    })


def make_double_bottom(n_total: int = 130) -> pd.DataFrame:
    """W-shape: down → bottom1 → up → bottom2 → up past neckline."""
    closes: list[float] = []
    # Initial descent from 100 to 60
    closes += list(np.linspace(100, 60, 30))
    # First bottom + rally to neckline 80
    closes += list(np.linspace(60, 80, 20))
    # Pullback to second bottom 62 (slightly higher = 짝궁둥이)
    closes += list(np.linspace(80, 62, 20))
    # Final rally past neckline 80 → 95
    closes += list(np.linspace(62, 95, 30))
    # Pad
    while len(closes) < n_total:
        closes.append(closes[-1] * (1 + np.random.default_rng(0).normal(0, 0.005)))
    return _to_df(closes)


def make_double_top(n_total: int = 130) -> pd.DataFrame:
    """M-shape: up → top1 → down → top2 → down past neckline."""
    closes: list[float] = []
    closes += list(np.linspace(60, 100, 30))
    closes += list(np.linspace(100, 80, 20))
    closes += list(np.linspace(80, 98, 20))   # slightly lower top = weakening
    closes += list(np.linspace(98, 65, 30))
    while len(closes) < n_total:
        closes.append(closes[-1] * 0.998)
    return _to_df(closes)


def make_inverse_hns(n_total: int = 200) -> pd.DataFrame:
    """Three lows: shoulder-head-shoulder, head lowest, breakout up.
    Uses sharp V-turns at each pivot so swing detection picks them up."""
    closes: list[float] = []
    # Pre-context (so swing detector has bars before left shoulder)
    closes += [110.0] * 5
    closes += list(np.linspace(110, 72, 20))   # descend to left shoulder 72
    closes += [72.0]                            # explicit low pivot
    closes += list(np.linspace(72, 88, 12))    # rally
    closes += [88.0]                            # peak1
    closes += list(np.linspace(88, 60, 18))    # head (deepest) 60
    closes += [60.0]                            # explicit head low
    closes += list(np.linspace(60, 87, 18))    # rally back
    closes += [87.0]                            # peak2 ≈ neckline
    closes += list(np.linspace(87, 73, 14))    # right shoulder ≈ left
    closes += [73.0]
    closes += list(np.linspace(73, 110, 25))   # breakout above neckline
    while len(closes) < n_total:
        closes.append(closes[-1] * 1.001)
    return _to_df(closes)


def make_hns(n_total: int = 160) -> pd.DataFrame:
    """H&S top: shoulder-head-shoulder peaks, head highest, break down."""
    closes: list[float] = []
    closes += list(np.linspace(60, 90, 25))    # rise to left shoulder
    closes += list(np.linspace(90, 75, 15))    # pullback
    closes += list(np.linspace(75, 110, 25))   # head (highest)
    closes += list(np.linspace(110, 75, 25))   # back to neckline
    closes += list(np.linspace(75, 92, 15))    # right shoulder (similar)
    closes += list(np.linspace(92, 55, 30))    # breakdown below neckline
    while len(closes) < n_total:
        closes.append(closes[-1] * 0.999)
    return _to_df(closes)


def make_triple_bottom(n_total: int = 240) -> pd.DataFrame:
    closes: list[float] = []
    closes += [105.0] * 5
    closes += list(np.linspace(105, 60, 25))
    closes += [60.0]
    closes += list(np.linspace(60, 78, 15))
    closes += [78.0]
    closes += list(np.linspace(78, 61, 15))
    closes += [61.0]
    closes += list(np.linspace(61, 79, 15))
    closes += [79.0]
    closes += list(np.linspace(79, 62, 15))
    closes += [62.0]
    closes += list(np.linspace(62, 95, 30))
    while len(closes) < n_total:
        closes.append(closes[-1] * 1.001)
    return _to_df(closes)


def make_triple_top(n_total: int = 240) -> pd.DataFrame:
    closes: list[float] = []
    closes += [55.0] * 5
    closes += list(np.linspace(55, 100, 25))
    closes += [100.0]
    closes += list(np.linspace(100, 82, 15))
    closes += [82.0]
    closes += list(np.linspace(82, 99, 15))
    closes += [99.0]
    closes += list(np.linspace(99, 81, 15))
    closes += [81.0]
    closes += list(np.linspace(81, 98, 15))
    closes += [98.0]
    closes += list(np.linspace(98, 65, 30))
    while len(closes) < n_total:
        closes.append(closes[-1] * 0.999)
    return _to_df(closes)


def make_random_walk(n: int = 260, seed: int = 7) -> pd.DataFrame:
    """Pure random walk — should rarely fire patterns; when it does, the
    invariants must still hold."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.02, n).cumsum()
    closes = 100 * np.exp(rets)
    return _to_df(list(closes))


# ─────────────────────────────────────────────────────────────────────
# Invariants
# ─────────────────────────────────────────────────────────────────────

def _check_plan_invariant(pattern, ctx: str) -> None:
    """Every Pattern's (entry, stop, target) must be internally consistent."""
    if pattern is None:
        return
    e, s, t = pattern.entry, pattern.stop, pattern.target
    if e is None or s is None or t is None:
        return
    d = pattern.direction
    if d == "bullish":
        assert s < e, (
            f"{ctx} bullish {pattern.kind}: stop {s:.2f} >= entry {e:.2f} (loss is upward!)"
        )
        assert e <= t, (
            f"{ctx} bullish {pattern.kind}: target {t:.2f} < entry {e:.2f} (target below entry!)"
        )
        assert s < t, (
            f"{ctx} bullish {pattern.kind}: stop {s:.2f} >= target {t:.2f}"
        )
    elif d == "bearish":
        assert e < s, (
            f"{ctx} bearish {pattern.kind}: entry {e:.2f} >= stop {s:.2f} (stop below entry for a short!)"
        )
        assert t <= e, (
            f"{ctx} bearish {pattern.kind}: target {t:.2f} > entry {e:.2f} (short target above entry!)"
        )
        assert t < s, (
            f"{ctx} bearish {pattern.kind}: target {t:.2f} >= stop {s:.2f}"
        )


# ─────────────────────────────────────────────────────────────────────
# Per-detector happy-path tests
# ─────────────────────────────────────────────────────────────────────

def test_double_bottom_detects_and_invariant():
    df = make_double_bottom()
    p = detect_double_bottom(df)
    assert p is not None, "double_bottom should fire on a textbook W shape"
    assert p.direction == "bullish"
    _check_plan_invariant(p, "synthetic-double-bottom")


def make_higher_right_double_bottom(n_total: int = 130) -> pd.DataFrame:
    """Book's "짝궁둥이 쌍바닥" variant: L2 noticeably higher than L1
    (책 p256: 가장 강력한 매수). L2/L1 gap ~9% — within tol 13% even
    after wick jitter expansion."""
    closes: list[float] = []
    closes += list(np.linspace(110, 60, 25))    # descent to L1 ~60
    closes += list(np.linspace(60, 78, 18))     # rally to neckline ~78
    closes += list(np.linspace(78, 66, 14))     # L2 ~66 — higher than L1 (~10%)
    closes += list(np.linspace(66, 95, 28))     # breakout above neckline
    while len(closes) < n_total:
        closes.append(closes[-1] * 1.002)
    return _to_df(closes)


def test_higher_right_double_bottom_fires_and_flagged():
    """Phase 2 fix: a 짝궁둥이 쌍바닥 (L2 ~17% above L1) must fire and
    stamp extra['higher_right']=True. This is the bullish counterpart
    to the Kakao weakening-top case — symmetric variant detection."""
    df = make_higher_right_double_bottom()
    p = detect_double_bottom(df)
    assert p is not None, "짝궁둥이 쌍바닥 should fire (L2 above L1, distance=3 fix)"
    assert p.direction == "bullish"
    assert p.extra.get("higher_right") is True, (
        f"higher_right flag not set. extra={p.extra}"
    )
    _check_plan_invariant(p, "synthetic-higher-right-bottom")


def test_double_bottom_NEVER_completed_below_neckline():
    """Regression for 068930.KQ 2026-05-21: 쌍바닥 검출 후 last_close 가
    neckline 한참 아래 (8460 vs 9180 = -8 %) 인데도 completed=True 로
    stamp 되어 STRONG_BUY + entry_plan 이 빌드됐던 케이스. 책 정신 (p254):
    쌍바닥 완성 = 네크라인 돌파.

    Invariant 검증: 어떤 input 으로도 detector 가 fire 했다면
        last_close <= neckline → completed=False
    가 반드시 성립.

    Random-walk 50개 chart 로 fuzz 검사 — `completed=True` 인 모든
    케이스에서 last_close > neckline 도 만족하는지 확인.
    """
    rng = np.random.default_rng(seed=42)
    violations: list[str] = []
    for trial in range(50):
        n = 130
        dates = pd.date_range("2024-01-01", periods=n, freq="W-FRI")
        # Random walk + W-shape bias
        walk = np.cumsum(rng.normal(0, 1, n)) + 100
        for i in range(n):
            if 50 <= i < 70:  # bias down to low1
                walk[i] -= 8
            elif 80 <= i < 100:  # bias down to low2
                walk[i] -= 6
        walk = np.clip(walk, 50, 200)
        df = pd.DataFrame({
            "date": dates,
            "open": walk, "high": walk * 1.01, "low": walk * 0.99,
            "close": walk, "volume": rng.integers(50_000, 200_000, n),
        })
        p = detect_double_bottom(df)
        if p is None or not p.completed:
            continue
        neckline = (p.extra or {}).get("neckline")
        last_close = float(df["close"].iloc[-1])
        if neckline is not None and last_close <= neckline:
            violations.append(
                f"trial {trial}: completed=True with close {last_close:.1f} "
                f"<= neckline {neckline:.1f}"
            )
    assert not violations, (
        f"쌍바닥 completed 가 네크라인 돌파 조건 미준수 ({len(violations)} 건):\n"
        + "\n".join(violations[:5])
    )


def test_double_top_detects_and_invariant():
    df = make_double_top()
    p = detect_double_top(df)
    assert p is not None, "double_top should fire on a textbook M shape"
    assert p.direction == "bearish"
    _check_plan_invariant(p, "synthetic-double-top")


def make_weakening_double_top(n_total: int = 130) -> pd.DataFrame:
    """Book's "약화 쌍봉" variant: H2 markedly lower than H1.

    Models the Kakao 2021 case structure (book p264-265):
      - H1 at ~100 (analogous to 173K)
      - intervening trough at ~82 (the neckline)
      - H2 at ~88 (analogous to 153K — 12 % below H1, well outside the
        old tol=5 % cap)
      - breakdown to ~60 below neckline (analogous to 118K break)

    Phase 2 fix should make this fire AND flag extra['weakening']=True.
    """
    closes: list[float] = []
    closes += list(np.linspace(60, 100, 30))    # rise to first top
    closes += list(np.linspace(100, 82, 18))    # pull back to neckline ~82
    closes += list(np.linspace(82, 88, 14))     # second top — LOWER (~12%)
    closes += list(np.linspace(88, 60, 28))     # breakdown
    while len(closes) < n_total:
        closes.append(closes[-1] * 0.998)
    return _to_df(closes)


def test_weakening_double_top_fires_and_flagged():
    """The Phase 2 fix (Kakao 2021 case): a double top with H2 ~12 %
    lower than H1 should now fire and stamp extra['weakening']=True.
    Anti-regression: if tol gets tightened back below ~12 % or the
    weakening flag stops being written, this test fails."""
    df = make_weakening_double_top()
    p = detect_double_top(df)
    assert p is not None, (
        "Weakening double top (H2 ~12% below H1) should fire — Phase 2 "
        "set tol=0.12 specifically to admit this variant. Did tol regress?"
    )
    assert p.direction == "bearish"
    assert p.extra.get("weakening") is True, (
        f"weakening flag not set. extra={p.extra}"
    )
    _check_plan_invariant(p, "synthetic-weakening-double-top")


def test_inverse_hns_invariant_when_detected():
    """If inverse H&S fires on a textbook shape, the plan must be valid.
    The detector is conservative and may pass on synthetic data — we
    check the invariant only when it does fire."""
    df = make_inverse_hns()
    p = detect_reverse_head_and_shoulders(df)
    if p is None:
        pytest.skip("detector did not fire on this synthetic shape")
    assert p.direction == "bullish"
    _check_plan_invariant(p, "synthetic-inverse-hns")


def test_hns_detects_and_invariant():
    df = make_hns()
    p = detect_head_and_shoulders(df)
    assert p is not None, "H&S should fire on textbook shape"
    assert p.direction == "bearish"
    _check_plan_invariant(p, "synthetic-hns")


def test_triple_bottom_invariant():
    df = make_triple_bottom()
    p = detect_triple_bottom(df)
    if p is not None:
        assert p.direction == "bullish"
        _check_plan_invariant(p, "synthetic-triple-bottom")


def test_triple_top_invariant():
    df = make_triple_top()
    p = detect_triple_top(df)
    if p is not None:
        assert p.direction == "bearish"
        _check_plan_invariant(p, "synthetic-triple-top")


# ─────────────────────────────────────────────────────────────────────
# The regression: H&S with very old completion — neckline must NOT
# get extrapolated below the head.
# ─────────────────────────────────────────────────────────────────────

def test_inverse_hns_old_pattern_neckline_still_above_head():
    """Reproduces the SK텔레콤 bug shape: inverse H&S that completed
    long ago, then price kept rising. Bug was: linear neckline extrapolated
    forward 50+ bars ended up below the head, target was projected
    downward, target < entry. With the fix, neckline is fixed at the
    actual between-highs extreme — invariant must hold."""
    closes: list[float] = []
    # Build inverse H&S in the first 100 bars
    closes += list(np.linspace(100, 65, 20))
    closes += list(np.linspace(65, 80, 15))
    closes += list(np.linspace(80, 55, 15))     # head = 55
    closes += list(np.linspace(55, 78, 15))
    closes += list(np.linspace(78, 67, 15))
    closes += list(np.linspace(67, 85, 20))     # break above neckline ~78
    # Then a long run-up another year — this is what triggered the bug
    closes += list(np.linspace(85, 200, 60))
    df = _to_df(closes)
    p = detect_reverse_head_and_shoulders(df)
    if p is None:
        return    # acceptable — detector may not fire; the invariant is per-fire
    head_p = p.extra.get("head", {}).get("price")
    neckline = p.extra.get("neckline")
    assert neckline is not None and head_p is not None
    assert neckline > head_p, (
        f"inverse H&S neckline {neckline:.2f} fell to/below head {head_p:.2f} "
        f"— extrapolation bug regressed"
    )
    _check_plan_invariant(p, "old-inverse-hns")


def test_hns_top_old_pattern_neckline_below_head():
    """Symmetric regression for the H&S top detector."""
    closes: list[float] = []
    closes += list(np.linspace(60, 95, 20))
    closes += list(np.linspace(95, 80, 15))
    closes += list(np.linspace(80, 110, 15))     # head = 110
    closes += list(np.linspace(110, 78, 15))
    closes += list(np.linspace(78, 92, 15))
    closes += list(np.linspace(92, 65, 20))      # breakdown below neckline ~80
    closes += list(np.linspace(65, 30, 60))      # long decline
    df = _to_df(closes)
    p = detect_head_and_shoulders(df)
    if p is None:
        return
    head_p = p.extra.get("head", {}).get("price")
    neckline = p.extra.get("neckline")
    assert neckline is not None and head_p is not None
    assert neckline < head_p
    _check_plan_invariant(p, "old-hns")


# ─────────────────────────────────────────────────────────────────────
# Random-walk fuzz: invariants must NEVER break on noise
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", list(range(20)))
def test_invariants_hold_on_random_walks(seed: int):
    """20 different random walks. Whatever detectors fire, every plan
    (entry, stop, target) must satisfy the directional invariant."""
    df = make_random_walk(n=260, seed=seed)
    patterns = detect_all(df)
    for p in patterns:
        _check_plan_invariant(p, f"random-walk-seed-{seed}")


# ─────────────────────────────────────────────────────────────────────
# analyzer.entry_block invariants
# ─────────────────────────────────────────────────────────────────────

def test_analyzer_entry_block_invariant_on_synthetic():
    """Across multiple synthetic charts, when analyzer surfaces an
    entry_plan it must satisfy stop < entry, and target (if present)
    must be ≥ entry. target=None is valid for the MA-trailing fallback."""
    for name, df in [
        ("double_bottom", make_double_bottom(n_total=260)),
        ("inverse_hns",   make_inverse_hns(n_total=260)),
        ("rwalk_3",       make_random_walk(seed=3)),
        ("rwalk_11",      make_random_walk(seed=11)),
    ]:
        r = analyze_ticker(name, df.copy())
        ep = r.get("entry_plan")
        if ep is None:
            continue
        s, e, t = ep.get("stop"), ep.get("entry"), ep.get("target")
        assert s is not None and e is not None, name
        assert s < e, f"{name}: entry_plan stop {s} >= entry {e}"
        # target may be None for the 10MA-trailing fallback path.
        if t is not None:
            assert e <= t, f"{name}: entry_plan target {t} < entry {e}"


def test_analyzer_entry_block_uses_tight_stop_for_runaway():
    """When price has run far above the pattern bottom, the entry_plan
    must surface the tighter trailing 주봉 10MA stop instead of the
    pattern's wide bottom-of-formation stop. Direct regression for the
    SK텔레콤 case (entry 100k, naive stop 49k, MA10-based stop ~89k)."""
    closes: list[float] = []
    closes += list(np.linspace(100, 50, 40))
    closes += list(np.linspace(50, 65, 20))
    closes += list(np.linspace(65, 51, 20))
    closes += list(np.linspace(51, 75, 20))
    closes += list(np.linspace(75, 100, 60))    # run-up far above pattern
    df = _to_df(closes, start_date="2023-01-01")
    r = analyze_ticker("runaway", df)
    ep = r.get("entry_plan")
    if ep is None:
        return    # if no bullish action fires, that's fine
    last_close = float(df["close"].iloc[-1])
    stop = ep["stop"]
    # Stop should not be more than 25% below current price for a fresh
    # entry — that was the bug's symptom.
    assert stop >= last_close * 0.75, (
        f"entry_plan stop {stop:.2f} is more than 25% below last close "
        f"{last_close:.2f} — trailing 10MA stop fallback regressed"
    )
