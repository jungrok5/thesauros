"""OOS verification of Samsung Electronics Cup-and-Handle 2024-2025.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p280-281.

Book's claim:
  - 2024/11/11 저점 49,900원 (-52.52% from prior peak)
  - Cup 형성 2024 하반기 ~ 2025 중반
  - Handle A/B: 240MA 근처
  - 2025/11/03 고점 112,400원 (+125% from low)
  - 책: 240MA 동시 돌파 = 더욱 강한 상승 자리
  - 윌리엄 오닐의 시그니처 기법 ('최고의 주식, 최적의 타이밍')

What this test verifies:
  1) Fixture data integrity — book's reported prices (49.9K low,
     112.4K high) reconcile with FDR fixture.
  2) System fires action_buy near book's handle date (mid-2025).
  3) System fires pattern_ma240_breakout near 2025-08 — the "240MA
     동시 돌파 더 강한 매수" the book specifically calls out.
  4) Pattern detector (Phase 2 #PATTERN_CUP_RELAXED fix, 2026-05-22):
     pattern_rounding_bottom (= Cup-with-Handle, slug "원형바닥") fires
     2025-09-12 with variant='v_recovery', confidence 0.75. The V-
     recovery variant added to detect_cup_and_handle handles the
     book's stylistic "deep V + handle + breakout" case (no matching
     left rim required).

Reuses fixture from test_samsung_5y_monthly_10ma — same ticker, same
date range.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import (
    fires_near, load_fixture, load_walk_snapshot,
)

_SLUG = "005930_samsung_5y_monthly_10ma"

# Book anchors (p281 chart):
_BOOK_LOW_DATE = date(2024, 11, 11)
_BOOK_LOW_PRICE = 49_900
_BOOK_HIGH_DATE = date(2025, 11, 3)
_BOOK_HIGH_PRICE = 112_400
# Handle is described as "240MA 부근" — approximate window mid-2025.
_BOOK_HANDLE_WINDOW_START = date(2025, 3, 1)
_BOOK_HANDLE_WINDOW_END = date(2025, 9, 30)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk():
    return load_walk_snapshot(_SLUG)


def _bar_close_at_or_near(fixture, target: date, granularity: str = "W") -> tuple[date, float]:
    """Closest bar of given granularity to target date. Returns (date, close)."""
    best: tuple[date, float] | None = None
    best_dist = None
    for b in fixture["bars"]:
        if b["granularity"] != granularity:
            continue
        d = date.fromisoformat(b["date"])
        dist = abs((d - target).days)
        if best_dist is None or dist < best_dist:
            best = (d, float(b["close"]))
            best_dist = dist
    if best is None:
        raise AssertionError(f"no {granularity} bar found in fixture")
    return best


# ─────────────────────────────────────────────────────────────────────
# Fixture sanity — book's quoted prices must reconcile
# ─────────────────────────────────────────────────────────────────────

def test_fixture_low_price_matches_book(fixture) -> None:
    """Weekly bar nearest 2024-11-11 should have a low within ~5%
    of the book's 49,900원. Weekly bars are W-FRI anchors so 11/11
    (Monday) maps to the Friday of that week or the prior — wider
    tolerance acceptable."""
    weekly_lows = [
        (b["date"], float(b["low"]))
        for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2024-11" in b["date"]
    ]
    assert weekly_lows, "no November 2024 weekly bars in fixture"
    week_min_low = min(low for _, low in weekly_lows)
    assert abs(week_min_low - _BOOK_LOW_PRICE) <= _BOOK_LOW_PRICE * 0.05, (
        f"Nov 2024 weekly low = {week_min_low:.0f}, book says ~{_BOOK_LOW_PRICE}. "
        "If diverging, FDR may have changed prices — re-pull the fixture."
    )


def test_fixture_high_price_matches_book(fixture) -> None:
    """Weekly bar nearest 2025-11-03 should have a high near the
    book's 112,400원 high."""
    weekly_highs = [
        (b["date"], float(b["high"]))
        for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2025-11" in b["date"]
    ]
    assert weekly_highs, "no November 2025 weekly bars in fixture"
    week_max_high = max(high for _, high in weekly_highs)
    assert abs(week_max_high - _BOOK_HIGH_PRICE) <= _BOOK_HIGH_PRICE * 0.10, (
        f"Nov 2025 weekly high = {week_max_high:.0f}, book says ~{_BOOK_HIGH_PRICE}. "
        "If diverging, re-pull fixture or check for splits/adjustments."
    )


# ─────────────────────────────────────────────────────────────────────
# System: action_buy near book's handle
# ─────────────────────────────────────────────────────────────────────

def test_action_buy_fires_in_handle_window(walk) -> None:
    """The book's handle is roughly 2025-Q2/Q3 (240MA 부근 정리 자리).
    Our action engine should flag a buy at some point in that window —
    that's where the user following the book's rule would enter."""
    buys = []
    for d in sorted(walk.keys()):
        if not (_BOOK_HANDLE_WINDOW_START <= d <= _BOOK_HANDLE_WINDOW_END):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                buys.append((d, st))
                break
    assert buys, (
        f"No action_buy/strong_buy in handle window "
        f"[{_BOOK_HANDLE_WINDOW_START}, {_BOOK_HANDLE_WINDOW_END}]. "
        "Book's case relies on a buy near the handle — missing it means "
        "a user following our alerts would not enter."
    )
    # First buy in window — characterize how early/late vs book's
    # rough handle-mid point (2025-06 estimate).
    first_buy_d = min(d for d, _ in buys)
    assert date(2025, 4, 1) <= first_buy_d <= date(2025, 8, 31), (
        f"First buy in handle window = {first_buy_d}. Expected in "
        "[2025-04, 2025-08] (book's handle zone). If shifted, check "
        "the ENTRY_LAG fresh-cross logic in analyze_multi_timeframe."
    )


# ─────────────────────────────────────────────────────────────────────
# System: 240MA breakout — the book's "더 강한 매수" signal
# ─────────────────────────────────────────────────────────────────────

def test_pattern_ma240_breakout_fires_in_window(walk) -> None:
    """Book p281: "핸들 자리에서 240이평선을 뚫는 경우 더욱 강한 상승
    자리". Our pattern_ma240_breakout MUST fire somewhere in the
    handle-through-rally window. Currently fires 2025-08-01."""
    hits = []
    for d in sorted(walk.keys()):
        if not (_BOOK_HANDLE_WINDOW_START <= d <= _BOOK_HIGH_DATE):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if "240" in st or "ma240" in st or "ma_240" in st:
                hits.append((d, st))
    assert hits, (
        "No 240MA-breakout signal fired between handle and book's high. "
        "Book specifically calls this out as the strong-buy version of "
        "cup-and-handle. If missing, detect_240ma_breakout may have "
        "tightened too far."
    )


# ─────────────────────────────────────────────────────────────────────
# Known gap (today): pattern_cup_and_handle doesn't fire
# ─────────────────────────────────────────────────────────────────────

def test_pattern_cup_handle_fires_with_v_recovery_variant(walk) -> None:
    """Phase 2 #PATTERN_CUP_RELAXED fix: a V-recovery cup-handle (no
    matching left rim) should fire with variant='v_recovery'. The
    pattern's signal_type is `pattern_rounding_bottom` (책 명칭
    "원형바닥 (Cup with Handle)" → slug "원형바닥" matches first).

    Currently first fires 2025-09-12 — exactly in the book's handle
    window. Required minimum: at least 1 fire between the handle
    window start and book's high date."""
    hits = []
    for d in sorted(walk.keys()):
        if not (_BOOK_HANDLE_WINDOW_START <= d <= _BOOK_HIGH_DATE):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st in ("pattern_rounding_bottom", "pattern_cup_and_handle"):
                hits.append((d, s))
    assert hits, (
        "No pattern_rounding_bottom/cup_and_handle fired in the book's "
        f"handle-through-high window [{_BOOK_HANDLE_WINDOW_START}, "
        f"{_BOOK_HIGH_DATE}]. #PATTERN_CUP_RELAXED V-recovery variant "
        "should catch this case — check detect_cup_and_handle."
    )
    # Variant flag — must come through params (Phase 2 _pattern_signals
    # change forwards detector's extra into params).
    variants = {s.get("params", {}).get("variant") for _, s in hits}
    assert "v_recovery" in variants, (
        f"None of the {len(hits)} cup fires marked variant=v_recovery. "
        f"Variants seen: {variants}. The Samsung 2024-2025 case is the "
        "canonical V-recovery — textbook can't match (no left rim)."
    )
