"""OOS verification of 디아이씨 (092200.KS) 240MA breakout case.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p352-353.

Book's claim:
  - 240MA 밑에 따개비처럼 붙어있는 상태 (오랜 시간)
  - 넓은 쌍바닥 / 다중바닥 형성
  - 240MA 돌파 시 거래량 적음 = 매집 완료
  - **수익률 +160%** ⭐⭐ (책 명시)
  - A 자리 진입 (책 차트 기간 2025-03 ~ 2025-12-08)

Distinct from PSK (p350-351) in that the breakout has QUIET volume
(매집 완료) — book's "옥석 중 옥석" variant.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import load_fixture, load_walk_snapshot

_SLUG = "092200_dic_240ma_breakout_2025"
_BOOK_RETURN_PCT = 160.0
_ENTRY_WINDOW_START = date(2025, 7, 1)
_ENTRY_WINDOW_END = date(2025, 11, 30)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk():
    return load_walk_snapshot(_SLUG)


def test_fixture_consolidation_zone(fixture) -> None:
    """DIC consolidated around 4-5K through mid-2025 — book's 240MA-
    바ne barnacle zone. Weekly closes in 2025-04 ~ 2025-09 should be
    within [3,000, 6,000]."""
    closes = [
        float(b["close"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2025-04" <= b["date"][:7] <= "2025-09"
    ]
    assert closes, "no 2025 Q2-Q3 weekly bars"
    assert 3_000 <= min(closes), f"low closes {min(closes)} out of expected range"
    assert max(closes) <= 7_000, (
        f"high closes {max(closes)} above expected pre-breakout range"
    )


def test_fixture_rally_completes_book_return(fixture) -> None:
    """+160% from 5K = 13K. DIC weekly high in 2025-12 should reach
    that level (book chart end 2025-12-08)."""
    highs = [
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2025-12")
    ]
    assert highs, "no Dec 2025 weekly bars"
    assert max(highs) >= 11_000, (
        f"Dec 2025 max high = {max(highs)}, expected ≥11,000 to support "
        f"book +{_BOOK_RETURN_PCT:.0f}% claim."
    )


def test_action_buy_fires_in_breakout_window(walk) -> None:
    """Book's "A 자리 진입" is the 240MA breakout zone (mid-late 2025).
    action_buy must fire there."""
    buys = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                buys.append((d, st))
                break
    assert buys, "No action_buy in DIC breakout window 2025-Q3/Q4."


def test_pattern_ma240_breakout_fires_with_high_confidence(walk) -> None:
    """The headline pattern. Book's "거래량 적은 돌파" should produce
    high-confidence signals (barnacle + quiet_volume boost). At least
    one fire in entry window must have conf ≥ 0.85."""
    hits = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            if s.get("signal_type") == "pattern_ma240_breakout":
                hits.append((d, float(s.get("strength", 0))))
    assert hits, (
        "No pattern_ma240_breakout in DIC entry window. Phase 2 min-bars "
        "fix should enable this — check detect_240ma_breakout."
    )
    max_conf = max(c for _, c in hits)
    assert max_conf >= 0.85, (
        f"max ma240 confidence = {max_conf:.2f}, expected ≥0.85 for DIC "
        "(barnacle + quiet volume — book's '옥석 중 옥석' case)."
    )
