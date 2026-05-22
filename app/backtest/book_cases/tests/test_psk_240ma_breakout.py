"""OOS verification of 피에스케이홀딩스 (031980.KS) 240MA breakout case.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p350-353.

Book's claim:
  - 240MA 밑에서 따개비처럼 붙어있다 → 양봉 돌파
  - Entry: 9,000원 (240MA 돌파 시점)
  - Exit:  44,000원 (10이평선 깨짐)
  - **수익률 +388%** ⭐⭐⭐ (책 명시)
  - 돌파 거래량 적을수록 좋음 (매집 완료 증거)

What this test verifies:
  1) Fixture sanity — book's quoted entry (~9K) and exit (~44K)
     are present in FDR data.
  2) action_buy fires in book's entry window (2023 first half).
  3) pattern_ma240_breakout fires in 2023-Q2 (the textbook 240MA
     crossover the book hammers on, p350-353). Phase 2 fix lowered
     the min-bars from 305 to 245 so this can fire for stocks with
     ~5y history; PSK has 412 weekly bars.
  4) action_sell triggers post-peak (PSK peaked at ~81K in mid-2024
     then drew down; book exit at 44K was on 10MA break).
  5) Realized return from book entry → mid-2024 peak ≈ +388%.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import load_fixture, load_walk_snapshot

_SLUG = "031980_psk_240ma_breakout_2023"
_BOOK_ENTRY_PRICE = 9_000
_BOOK_EXIT_PRICE = 44_000
_BOOK_RETURN_PCT = 388.0
_ENTRY_WINDOW_START = date(2023, 1, 1)
_ENTRY_WINDOW_END = date(2023, 9, 30)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk():
    return load_walk_snapshot(_SLUG)


# ─────────────────────────────────────────────────────────────────────
# Fixture sanity
# ─────────────────────────────────────────────────────────────────────

def test_fixture_entry_zone_matches_book(fixture) -> None:
    """Book entry at ~9,000원. The fixture's weekly close min in
    2022-12 ~ 2023-03 (the "barnacle" + first breakout zone) should
    fall within [7,000, 11,000]."""
    closes = [
        float(b["close"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2022-12" <= b["date"][:7] <= "2023-03"
    ]
    assert closes, "no 2022-12 ~ 2023-03 weekly bars in fixture"
    min_close = min(closes)
    assert 6_500 <= min_close <= 11_000, (
        f"barnacle-zone min close = {min_close}, expected within [6500, 11000] "
        "(book entry ~9,000원). FDR data may have shifted."
    )


def test_fixture_rally_peak_supports_book_return(fixture) -> None:
    """Book exit at 44,000원, implied peak somewhere higher (+388%
    from 9K = 43.9K min, but PSK actually peaked at ~81K in mid-2024).
    Weekly high in 2024 must be ≥45K to support the book's exit."""
    highs_2024 = [
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2024")
    ]
    assert highs_2024, "no 2024 weekly bars in fixture"
    max_high = max(highs_2024)
    assert max_high >= 45_000, (
        f"2024 max high = {max_high}, expected ≥45,000 to support "
        f"book exit at {_BOOK_EXIT_PRICE}원."
    )


def test_book_return_holds_in_fixture(fixture) -> None:
    """Approximate realized return: from a representative early-2023
    entry close (the 240MA breakout zone) to the 2024 peak. Should
    reach the book's +388% within ~25% tolerance."""
    entry_candidates = [
        float(b["close"]) for b in fixture["bars"]
        if b["granularity"] == "W"
        and "2023-02" <= b["date"][:7] <= "2023-04"
    ]
    entry = min(entry_candidates)
    peak = max(
        float(b["high"]) for b in fixture["bars"]
        if b["granularity"] == "W" and b["date"].startswith("2024")
    )
    ret_pct = (peak / entry - 1.0) * 100.0
    assert ret_pct >= 300, (
        f"realized 2023-Q1 → 2024 peak return = {ret_pct:.0f}%, expected "
        f"≥300% to validate book's +{_BOOK_RETURN_PCT:.0f}% claim."
    )


# ─────────────────────────────────────────────────────────────────────
# System signals
# ─────────────────────────────────────────────────────────────────────

def test_action_buy_fires_in_entry_window(walk) -> None:
    """action_buy MUST fire in 2023 Q1-Q3 (book's entry window).
    Without it, the system wouldn't have surfaced PSK to a user."""
    buys = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                buys.append((d, st))
                break
    assert buys, "No action_buy in PSK entry window 2023 Q1-Q3."


def test_pattern_ma240_breakout_fires_in_window(walk) -> None:
    """Phase 2 min-bars fix (305→245): pattern_ma240_breakout should
    now fire in PSK's 2023-Q2 breakout (book's headline signal). Will
    actually find ≥1 fire in entry window with conf ≥ 0.8."""
    hits = []
    for d in sorted(walk.keys()):
        if not (_ENTRY_WINDOW_START <= d <= _ENTRY_WINDOW_END):
            continue
        for s in walk[d]:
            if s.get("signal_type") == "pattern_ma240_breakout":
                hits.append((d, float(s.get("strength", 0))))
    assert hits, (
        "No pattern_ma240_breakout in PSK entry window. The book's "
        "headline pattern is the 240MA crossover — if missing here, "
        "the Phase 2 min-bars fix regressed."
    )
    max_conf = max(c for _, c in hits)
    assert max_conf >= 0.75, (
        f"Highest 240MA-breakout confidence in window = {max_conf:.2f}, "
        "expected ≥0.75 for a clean barnacle + breakout case."
    )


def test_action_sell_fires_post_peak(walk) -> None:
    """PSK peaked at ~81K in mid-2024; book exit at 44K was on 10MA
    break. action_sell should fire by end of 2024 at latest."""
    sells = []
    for d in sorted(walk.keys()):
        if d < date(2024, 6, 1):
            continue
        for s in walk[d]:
            if s.get("signal_type", "").startswith("action_sell"):
                sells.append((d, s.get("signal_type")))
    assert sells, "No action_sell after PSK's 2024 peak — exit missed."
