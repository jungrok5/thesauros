"""OOS verification of 엘앤씨바이오 (092070.KQ) 240MA-centered case.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p348-349.

Book's claim:
  - 240MA를 가운데 둔 쌍바닥 (한쪽 저점 240MA 아래, 다른쪽 위)
  - 240MA 매물 소화 메커니즘 → 강력 매수 신호
  - 2024/09 ~ 2025/11 chart window
  - Book shows ~18K → 30K trajectory (likely pre-split or chart-display
    prices; FDR adjusted shows ~8K → 16K which is the same 2:1
    magnitude move).

This test is weaker than other Phase 2 cases — book's specific
"240MA-centered double-bottom" pattern has no dedicated detector
(detect_dolbanji is the closest but operates on the 쌍바닥형 돌반지
pattern, which is different). We verify:

  1) Fixture sanity — FDR shows the 2024-12 low and 2025-Q4 recovery.
  2) action_buy fires somewhere in the recovery window.
  3) Realized return supports the move's magnitude.

Known gap (not fixed here): pattern_dolbanji / 240MA-centered
double-bottom isn't reliably detected on this case.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import load_fixture, load_walk_snapshot

_SLUG = "092070_lncbio_240ma_centered_2024"
_ENTRY_WINDOW_START = date(2025, 1, 1)
_ENTRY_WINDOW_END = date(2025, 6, 30)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk():
    return load_walk_snapshot(_SLUG)


def test_fixture_low_in_book_window(fixture) -> None:
    """The 2024-12 ~ 2025-01 zone should have weekly lows around the
    240MA — FDR adjusted shows ~8K low in this window."""
    lows = [
        float(b["low"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2024-11" <= b["date"][:7] <= "2025-01"
    ]
    assert lows, "no 2024-Q4 ~ 2025-Q1 weekly bars"
    assert min(lows) <= 9_000, (
        f"min low = {min(lows)}, expected ≤9,000 in the book's bottoming zone."
    )


def test_fixture_rally_present(fixture) -> None:
    """Recovery to ~16K by 2025-Q4 (book labels this as the post-
    240MA-centered-double-bottom rally)."""
    highs = [
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2025-08" <= b["date"][:7] <= "2025-12"
    ]
    assert highs, "no 2025 H2 weekly bars"
    assert max(highs) >= 14_000, (
        f"max high in 2025 H2 = {max(highs)}, expected ≥14,000 (book's "
        "rally completes around this level on adjusted basis)."
    )


def test_action_buy_fires_in_recovery_window(walk) -> None:
    """action_buy MUST fire in the recovery window 2025-Q1/Q2. Our
    earlier-than-book detection is acceptable."""
    buys = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                buys.append((d, st))
                break
    assert buys, "No action_buy in L&C Bio recovery window 2025-Q1/Q2."


def test_realized_return_supports_move(fixture) -> None:
    """From the 2024-12 low to 2025-Q4 peak — should be ≥50%
    (FDR adjusted; book's pre-adjusted figures are roughly double)."""
    entry = min(
        float(b["low"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2024-11" <= b["date"][:7] <= "2025-01"
    )
    peak = max(
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2025-08" <= b["date"][:7] <= "2025-12"
    )
    ret_pct = (peak / entry - 1.0) * 100.0
    assert ret_pct >= 50, (
        f"realized 2024-12 low → 2025 H2 peak = {ret_pct:.0f}%, expected ≥50%."
    )
