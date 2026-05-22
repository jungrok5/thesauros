"""OOS verification of SAMG엔터테인먼트 (419530.KQ) triple-bottom case.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p276-279.

Book's claim:
  - 2024 하반기 ~ 2025 초: 삼중바닥 A/B/C 형성 around ~10,500원
  - Entry C: 13,000원 (책 명시)
  - Exit: 72,000원 (10이평선 깨짐 자리)
  - **수익률 +450%** (책 명시)
  - 거래량 우상향 (A<B<C) — book's "strong" variant flag

What this test verifies:
  1) Fixture data integrity — book's quoted prices (low ~10K, rally
     to 70K+ in mid-2025) reconcile with FDR.
  2) action_buy fires in book's entry window (Oct 2024 ~ Feb 2025).
  3) pattern_triple_bottom fires near book's C entry (Jan-Feb 2025).
     Phase 2 fixes applied: tol 5%→13%, distance=3, min-bars 32,
     sliding-triplet scan (rather than "last 3 lows" which on SAMG
     picks up the deeper 2024-06 dip + later cluster as non-tol triplet).
  4) action_sell triggers when book exit zone arrives (2025-11 after
     price has come back below 10MA from the 5월~7월 rally peak).
  5) Realized return (book entry → rally peak) approximates +450%.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import (
    fires_near, load_fixture, load_walk_snapshot,
)

_SLUG = "419530_samg_triple_bottom_2024"
_BOOK_ENTRY_PRICE = 13_000
_BOOK_EXIT_PRICE = 72_000
_BOOK_RETURN_PCT = 450.0
# Book entry window — A/B/C bottoms span 2024-Q4 to 2025-Q1.
_ENTRY_WINDOW_START = date(2024, 9, 1)
_ENTRY_WINDOW_END = date(2025, 3, 31)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk():
    return load_walk_snapshot(_SLUG)


# ─────────────────────────────────────────────────────────────────────
# Fixture sanity — book prices reconcile with FDR
# ─────────────────────────────────────────────────────────────────────

def test_fixture_triple_bottom_low_matches_book(fixture) -> None:
    """Book quotes 삼중바닥 around ~10,500원. The fixture's lowest
    weekly close in 2024-08 ~ 2024-12 must be in [9,000, 13,000]
    (allows ~25% margin around book's stylistic 10.5K anchor)."""
    weekly_lows = [
        float(b["low"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2024-" in b["date"]
        and b["date"][5:7] in ("08", "09", "10", "11", "12")
    ]
    assert weekly_lows, "no 2024 H2 weekly bars in fixture"
    min_low = min(weekly_lows)
    assert 9_000 <= min_low <= 13_000, (
        f"2024 H2 weekly low = {min_low}, expected within [9000, 13000] "
        "(book triple-bottom zone ~10,500). FDR data may have shifted."
    )


def test_fixture_rally_peak_matches_book(fixture) -> None:
    """Book claims exit at 72,000원. FDR weekly high in 2025 should
    confirm a rally to ≥70K (book exit was the post-peak 10MA cross)."""
    weekly_highs_2025 = [
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2025")
    ]
    assert weekly_highs_2025, "no 2025 weekly bars in fixture"
    max_high = max(weekly_highs_2025)
    assert max_high >= 70_000, (
        f"2025 max weekly high = {max_high}, expected ≥70,000 to support "
        f"book's exit at {_BOOK_EXIT_PRICE}원."
    )


def test_book_return_holds_in_fixture(fixture) -> None:
    """Approximate realized return: from a representative entry close
    in book's C zone (around 13K) to the rally peak. Must be ≥350%
    (book says ~450%, give ~25% margin for entry-bar choice)."""
    # Pick a representative entry close — the lowest weekly close in
    # 2024-Q4 (book's "C 자리(13,000원)").
    entry_candidates = [
        float(b["close"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2024")
        and b["date"][5:7] in ("10", "11", "12")
    ]
    entry = min(entry_candidates)
    # Peak 2025 high.
    peak = max(
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2025")
    )
    ret_pct = (peak / entry - 1.0) * 100.0
    assert ret_pct >= 350, (
        f"Realized 2024-Q4 → 2025 peak return = {ret_pct:.0f}%, expected "
        f"≥350% to validate book's +{_BOOK_RETURN_PCT:.0f}% claim."
    )


# ─────────────────────────────────────────────────────────────────────
# System: action_buy in book's entry window
# ─────────────────────────────────────────────────────────────────────

def test_action_buy_fires_in_entry_window(walk) -> None:
    """action_buy MUST fire somewhere in the book's entry window
    (Oct 2024 ~ Mar 2025). Without it, a user following the system
    wouldn't have entered SAMG before the +450% move."""
    buys = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                buys.append((d, st))
                break
    assert buys, (
        f"No action_buy in entry window [{_ENTRY_WINDOW_START}, "
        f"{_ENTRY_WINDOW_END}]. SAMG +450% move missed."
    )


# ─────────────────────────────────────────────────────────────────────
# System: pattern_triple_bottom fires
# ─────────────────────────────────────────────────────────────────────

def test_pattern_triple_bottom_fires_near_book_C(walk) -> None:
    """Phase 2 detector fixes (tol 5%→13%, distance=3, min-bars 32,
    sliding-triplet scan) should make pattern_triple_bottom fire on
    SAMG's bottoming cluster. Book's C entry is around Dec 2024 ~ Feb
    2025 — currently fires from 2025-01-17, conf 0.56."""
    hits = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            if s.get("signal_type") == "pattern_triple_bottom":
                hits.append((d, s))
    assert hits, (
        "No pattern_triple_bottom in entry window. Phase 2 should have "
        "enabled this — check tol/distance/min-bars in detect_triple_bottom."
    )


# ─────────────────────────────────────────────────────────────────────
# System: exit signal after rally
# ─────────────────────────────────────────────────────────────────────

def test_action_sell_fires_after_rally(walk) -> None:
    """After SAMG's 5월~7월 2025 rally (peak ~99K) and subsequent
    drawdown, action_sell_short should fire by late-2025. Book's exit
    was at 72K when 10MA broke — that happened in Aug 2025."""
    sells = []
    for d in sorted(walk.keys()):
        if d < date(2025, 7, 1):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_sell"):
                sells.append((d, st))
    assert sells, (
        "No action_sell after the 2025 SAMG rally. Trend-end signal "
        "missing — user wouldn't have exited at book's price."
    )
    # Book's exit was at 72K → 10MA break. Our first sell ≤ end of 2025.
    first_sell = min(d for d, _ in sells)
    assert first_sell <= date(2025, 12, 31), (
        f"First sell {first_sell} too late — book exit zone is Q3 2025."
    )
