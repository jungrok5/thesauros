"""OOS verification of the Kakao 2019-2021 case from the book.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p264-265.
  - Entry  : 2019-04 월봉 10MA 돌파, close 24,000원
  - Exit   : 2021-09 월봉 10MA 깨짐 + 쌍봉 완성, close 118,000원
  - Return : ~+390% (close-to-close, no friction)

What this test verifies:
  1) Fixture data integrity — our FDR-pulled bars agree with the book's
     reported entry/exit prices within rounding (split-adjusted).
  2) Raw price math — +390% holds end-to-end.
  3) Our system DID flag a sell within ±6 weeks of the book's exit.
     (The exit is the load-bearing decision — missing it costs 50%+.)
  4) Our system fired SOME buy signal during the 2019-2021 uptrend.
     (We don't require exact-month-match; book is monthly, we're weekly.)
  5) Characterization of timing lag — bounded so a future regression
     would change the bound and force review.

Known limitations surfaced (TODO #PATTERN_TOL, #PATTERN_LOOKBACK):
  - `pattern_double_top` does NOT fire on this case despite the book
    showing the textbook M-shape, because:
      • detector's `lookback=120` requires 120 bars; monthly Kakao has
        only ~46 bars in this fixture window
      • detector's `tol=0.05` requires the two highs to differ by ≤5%
        — Kakao's 173K → 153K is 11% (book's "weakening 약화" variant)
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List

import pytest

from app.backtest.book_cases.walk_forward import (
    fires_near, load_fixture, load_walk_snapshot,
)

# Book-reported anchors.
_BOOK_ENTRY = date(2019, 4, 30)
_BOOK_EXIT = date(2021, 9, 30)
_BOOK_ENTRY_PRICE = 24_000
_BOOK_EXIT_PRICE = 118_000
_BOOK_RETURN_PCT = 390.0   # close-to-close, no friction
_SLUG = "035720_kakao_2019_2021_double_top"


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


@pytest.fixture(scope="module")
def walk() -> Dict[date, List[dict]]:
    return load_walk_snapshot(_SLUG)


# ─────────────────────────────────────────────────────────────────────
# (1) Fixture sanity — FDR-pulled prices align with the book's quoted figures
# ─────────────────────────────────────────────────────────────────────

def _monthly_close(fixture, target_iso: str) -> float:
    for b in fixture["bars"]:
        if b["granularity"] == "M" and b["date"] == target_iso:
            return float(b["close"])
    raise AssertionError(f"no monthly bar dated {target_iso}")


def test_fixture_entry_price_matches_book(fixture) -> None:
    """2019-04-30 monthly close should be ~24,000원 (within 200원)."""
    c = _monthly_close(fixture, "2019-04-30")
    assert abs(c - _BOOK_ENTRY_PRICE) <= 200, (
        f"fixture says 2019-04-30 close={c}, book says ~{_BOOK_ENTRY_PRICE}. "
        "If this diverges, either FDR changed (re-pull) or the book is on "
        "pre-split prices."
    )


def test_fixture_exit_price_matches_book(fixture) -> None:
    """2021-09-30 monthly close should be ~118,000원 (within 500원)."""
    c = _monthly_close(fixture, "2021-09-30")
    assert abs(c - _BOOK_EXIT_PRICE) <= 500, (
        f"fixture says 2021-09-30 close={c}, book says ~{_BOOK_EXIT_PRICE}."
    )


def test_book_return_holds_in_fixture(fixture) -> None:
    """Close-to-close from 2019-04-30 to 2021-09-30 should reproduce
    the book's +390% (raw, no friction)."""
    entry = _monthly_close(fixture, "2019-04-30")
    exit_ = _monthly_close(fixture, "2021-09-30")
    ret_pct = (exit_ / entry - 1.0) * 100.0
    assert ret_pct == pytest.approx(_BOOK_RETURN_PCT, abs=5.0), (
        f"fixture realised return = {ret_pct:.1f}%, book says ~{_BOOK_RETURN_PCT}%"
    )


# ─────────────────────────────────────────────────────────────────────
# (2) System-level: did we flag the exit?
# ─────────────────────────────────────────────────────────────────────

def test_system_flagged_exit_near_book_date(walk) -> None:
    """Within ±6 weeks of the book's 2021-09-30 exit, our system MUST
    have surfaced at least one bearish action signal (action_sell* /
    action_sell_short). Missing this would mean a user following our
    system held through the whole drawdown."""
    hits = fires_near(walk, _BOOK_EXIT,
                      signal_type_prefix="action_sell",
                      window_weeks=6)
    assert hits, (
        "No action_sell* signal within ±6 weeks of 2021-09-30. "
        "Book exit was on 월봉 10MA 깨짐 + 쌍봉 — at minimum our action "
        "engine should flip bearish here."
    )
    # Currently fires at 2021-10-01 (1 week late). Bound so it doesn't
    # silently drift.
    first_hit = min(d for d, _ in hits)
    days_late = (first_hit - _BOOK_EXIT).days
    assert -14 <= days_late <= 14, (
        f"first sell signal {first_hit} is {days_late}d off from book — "
        "outside ±2-week tolerance, investigate"
    )


# ─────────────────────────────────────────────────────────────────────
# (3) System-level: did we catch the uptrend at all?
# ─────────────────────────────────────────────────────────────────────

def test_system_flagged_buy_during_uptrend(walk) -> None:
    """Somewhere between book's entry (2019-04) and exit (2021-09), our
    action engine should have fired at least one buy signal. We're
    deliberately permissive about WHEN — the book is monthly-driven
    (10MA monthly), we're weekly, so a lag is expected."""
    in_uptrend = []
    for d, sigs in walk.items():
        if not (_BOOK_ENTRY <= d <= _BOOK_EXIT):
            continue
        for s in sigs:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                in_uptrend.append((d, st))
    assert in_uptrend, (
        "No buy signal fired anywhere in the 2019-04 → 2021-09 window. "
        "Either the analyzer regressed or the fixture is stale."
    )


def test_system_entry_lag_is_bounded(walk) -> None:
    """How late was our first buy vs the book's 2019-04 entry?

    The book sees the breakout at monthly close. We see it on weekly
    bars + weekly MA crossovers, so a lag of weeks-to-months is
    expected. Bound the lag so any drift triggers explicit review:
      - lag < 0  → we got EARLIER than the book (good — review & widen)
      - lag in [0, 50w] → currently ~33w
      - lag > 50w → regressed → investigate

    The point isn't to track an exact number; it's to make the gap
    visible so it can be improved by Phase 2.1 (monthly-aware action).
    """
    first_buy = None
    for d in sorted(walk.keys()):
        if d < _BOOK_ENTRY:
            continue
        for s in walk[d]:
            st = s.get("signal_type", "")
            if st.startswith("action_buy") or st.startswith("action_strong_buy"):
                first_buy = d
                break
        if first_buy:
            break
    assert first_buy is not None, "no buy signal after book entry — impossible if test 3 passed"
    lag_weeks = (first_buy - _BOOK_ENTRY).days / 7
    assert 0 <= lag_weeks <= 50, (
        f"entry lag = {lag_weeks:.1f} weeks (first_buy={first_buy}). "
        "Outside the expected [0, 50w] envelope. If we got earlier, that's "
        "a win — tighten the bound. If later, investigate."
    )


# ─────────────────────────────────────────────────────────────────────
# (4) Known-gap characterization — pattern_double_top did NOT fire
# ─────────────────────────────────────────────────────────────────────

def test_pattern_double_top_does_not_fire_today(walk) -> None:
    """Currently our detect_double_top does NOT pick up the Kakao M-top
    because the two highs differ by ~11% (173K vs 153K) while the
    detector's tol is 5%, and because monthly bars (46) are below the
    lookback floor of 120.

    This test pins down the current gap. When we improve the detector
    (TODO #PATTERN_TOL / #PATTERN_LOOKBACK), this test will fail and
    we will flip the assertion to "MUST fire near 2021-09".
    """
    hits = fires_near(walk, _BOOK_EXIT,
                      signal_type_prefix="pattern_doubletop",
                      window_weeks=12)
    # Also check the snake_case variant 'pattern_double_top' which is
    # what extract_signals would slugify into (handle either spelling).
    hits += fires_near(walk, _BOOK_EXIT,
                       signal_type_prefix="pattern_double_top",
                       window_weeks=12)
    assert hits == [], (
        "pattern_double_top fired on Kakao — improvement! Update this "
        "test to assert presence, and close TODO #PATTERN_TOL/LOOKBACK."
    )
