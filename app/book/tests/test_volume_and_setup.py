"""Volume-case + MA-convergence setup detectors.

Regression for the 국보디자인 case (2026-05-22): zone=middle / trend=up /
vol_ratio=0.62 used to fall to case 0 "분류 불명확" and the analyzer
missed the "수렴기 + 거래량 감소" book pattern. Plus MA 10/20/60 had
squeezed within ~3 % around the price — clearly a 매복 setup — but no
detector caught it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.book.volume import classify_volume_case
from app.book.patterns import detect_ma_convergence_setup


def _frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    if volumes is None:
        volumes = [10_000] * n
    arr = np.asarray(closes, dtype=float)
    vol = np.asarray(volumes, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="W-FRI"),
        "open": arr, "high": arr * 1.01, "low": arr * 0.99,
        "close": arr, "adj_close": arr,
        "volume": vol,
    })


# ─────────────────────────────────────────────────────────────────────
# Volume case 12 — 수렴기 거래량 감소
# ─────────────────────────────────────────────────────────────────────

def test_volume_case_12_dries_up_during_consolidation():
    """Mid-zone price (range 40-100, current 70), 20-bar trend
    sideways, last-10 volume ≈ 0.47 × prior-10. Should fire case 12,
    not case 0 (분류 불명확) and not case 8 (top + volume drop)."""
    closes = (
        [40] * 30
        + list(np.linspace(40, 100, 80))
        + list(np.linspace(100, 70, 30))
        + [70, 71, 69, 70, 71, 70, 69, 70, 71, 70]
        + [70, 71, 69, 70, 71, 70, 69, 70, 71, 70]
    )
    vols = [10_000] * (len(closes) - 20) + [15_000] * 10 + [7_000] * 10
    df = _frame(closes, vols)
    vc = classify_volume_case(df)
    assert vc is not None
    assert vc.case == 12, f"expected case 12, got case {vc.case} ({vc.label_kr})"
    assert vc.direction == "bullish"


def test_volume_case_3_bottom_volume_surge_still_wins():
    """A volume surge at the bottom must still trigger case 3, not the
    new case 12."""
    closes = (
        list(np.linspace(100, 50, 100))    # crash
        + [51, 50, 52, 53]                  # bottom forming
    )
    vols = [10_000] * 100 + [50_000, 80_000, 100_000, 120_000]
    df = _frame(closes, vols)
    vc = classify_volume_case(df)
    assert vc is not None
    assert vc.case == 3, f"expected case 3 (bottom surge), got case {vc.case}"


def test_volume_case_0_only_for_truly_unclassified():
    """If trend is up + volume is normal (not dropping, not surging),
    we should NOT fire case 12. Falls through to case 0 or another."""
    closes = list(np.linspace(50, 70, 130))
    vols = [10_000] * 130   # flat volume
    df = _frame(closes, vols)
    vc = classify_volume_case(df)
    assert vc is not None
    # Case 12 requires VOL_DOWN; flat volume should not trigger it.
    assert vc.case != 12, f"expected non-12, got case {vc.case}"


# ─────────────────────────────────────────────────────────────────────
# detect_ma_convergence_setup — Forking setup (NOT fired yet)
# ─────────────────────────────────────────────────────────────────────

def test_setup_fires_on_tight_convergence_and_flat_box():
    """Long climb + extended flat plateau so MA 10/20/60 all converge
    at ~90. Final 4 bars in a tight ±1 % box. Detector should fire as
    direction=neutral / completed=False (wait state)."""
    closes = (
        [50] * 30
        + list(np.linspace(50, 90, 30))
        + [90] * 100                # long flat so MA-60 also = 90
        + [89, 90, 91, 90]          # tight box ~2 %
    )
    df = _frame(closes)
    p = detect_ma_convergence_setup(df)
    assert p is not None, "convergence setup should fire on a flat squeeze"
    assert p.direction == "neutral"
    assert p.completed is False, "setup is wait-state, not completed"
    assert "수렴" in p.kind or "매복" in p.kind


def test_setup_does_not_fire_when_breakout_already_happened():
    """If the last bar is a strong bullish breakout candle, this is the
    Forking FIRED state (handled by detect_forking) — setup detector
    must not duplicate-fire."""
    closes = (
        [50] * 30
        + list(np.linspace(50, 90, 30))
        + [90] * 100
        + [89, 90, 91, 90]
        + [98]   # strong +8% bullish breakout
    )
    df = _frame(closes)
    p = detect_ma_convergence_setup(df)
    assert p is None, "setup should NOT fire after the trigger candle"


def test_setup_does_not_fire_on_wide_spread():
    """If MAs are far apart (early in a strong trend), it's not a
    convergence — detector must return None."""
    closes = list(np.linspace(50, 120, 80))   # steady climb, MAs spread
    df = _frame(closes)
    p = detect_ma_convergence_setup(df)
    assert p is None


def test_setup_does_not_fire_on_wide_price_range():
    """Tight MAs but wildly swinging closes — not the calm consolidation
    book describes."""
    closes = (
        list(np.linspace(50, 100, 70))
        + [100, 120, 80, 100]   # ±20 % swings — too volatile
    )
    df = _frame(closes)
    p = detect_ma_convergence_setup(df)
    assert p is None
