"""OOS verification of the Samsung Electronics 5-year monthly 10MA case.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p318-319.

Book's claim, verbatim:
  - 5년간 (2021-01 ~ 2026-01) 삼성전자 월봉 10MA 매매
  - 진입 4번 → 3 수익, 1 손실
  - 손실 미미, 수익 훨씬 큼 (비대칭 손익)
  - "월봉 10MA 가 가장 객관적인 추세선" (저자의 10년 / 3만 시간 결론)

Unlike the Kakao case (which checks whether OUR analyzer surfaces a
specific book-identified signal), this test directly implements the
book's stated rule — monthly 10MA crossover — and checks whether
applying the rule reproduces the book's numerical claim. So this is a
verification of the BOOK, not of our analyzer.

What's verified:
  1) 4 trades overlap the observation window (matches book exactly).
  2) ≥2 wins out of 3 closed (book says "3 wins" but counts the open
     position as a forming-win; we conservatively only count closed).
  3) The open trade IS profitable mark-to-market at window end
     (verifies the book's "3 of 4 winning" claim with the open included).
  4) Asymmetry > 2.0 (avg_win / |avg_loss|) — book's "손실 미미, 수익
     훨씬 큼" claim, the most important qualitative point of the chapter.
  5) Worst trade is small (≤10% loss). Book: "손실 미미".
"""
from __future__ import annotations

from datetime import date

import pytest

from app.backtest.book_cases.walk_forward import load_fixture
from app.backtest.book_cases.monthly_10ma_strategy import (
    Trade, backtest_10ma, load_monthly_bars, summarize,
)

_SLUG = "005930_samsung_5y_monthly_10ma"
_WINDOW_START = date(2021, 1, 1)
_WINDOW_END = date(2026, 1, 31)


@pytest.fixture(scope="module")
def trades() -> list[Trade]:
    fx = load_fixture(_SLUG)
    m = load_monthly_bars(fx)
    return backtest_10ma(m, start=_WINDOW_START, end=_WINDOW_END)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(_SLUG)


# ─────────────────────────────────────────────────────────────────────
# Trade count
# ─────────────────────────────────────────────────────────────────────

def test_four_trades_in_book_window(trades) -> None:
    """The book says 4 entries on Samsung 2021-01 ~ 2026-01. Our
    overlap-inclusive crossover count must match — any drift means our
    MA computation or our crossover logic diverged from the book's
    visual reading."""
    assert len(trades) == 4, (
        f"Expected 4 trades (book p319), got {len(trades)}. "
        "Either FDR data changed (re-pull fixture) or the strategy "
        "logic regressed."
    )


# ─────────────────────────────────────────────────────────────────────
# Win/loss distribution
# ─────────────────────────────────────────────────────────────────────

def test_closed_trades_have_at_least_two_wins(trades) -> None:
    """The book claims 3 of 4 trades won — but 1 trade is still open
    at the end of the 5-year window. Of the 3 CLOSED, 2 must be wins
    for the book's "predominantly winning" claim to hold."""
    s = summarize(trades)
    assert s["n_closed"] >= 3, f"expected ≥3 closed trades, got {s['n_closed']}"
    assert s["n_wins"] >= 2, (
        f"closed wins = {s['n_wins']} / {s['n_closed']}. "
        "Book says 3 of 4 — at minimum 2 of 3 closed should be winners."
    )


def test_open_trade_is_profitable_mark_to_market(trades, fixture) -> None:
    """The 4th (open) trade is at +mark-to-market at the book's window
    end. Without this, the book's "3 of 4 winning" claim doesn't hold;
    the open trade is the third winner."""
    open_trades = [t for t in trades if t.exit_date is None]
    assert len(open_trades) == 1, f"expected 1 open trade, got {len(open_trades)}"
    open_t = open_trades[0]

    # Find the close on the last monthly bar within the book window.
    last_close = None
    last_date = None
    for b in fixture["bars"]:
        if b["granularity"] != "M":
            continue
        d = date.fromisoformat(b["date"])
        if d <= _WINDOW_END and (last_date is None or d > last_date):
            last_date = d
            last_close = float(b["close"])
    assert last_close is not None, "no monthly bar within book window"

    mtm_pct = (last_close / open_t.entry_price - 1.0) * 100.0
    assert mtm_pct > 0, (
        f"open trade entered {open_t.entry_date} @ {open_t.entry_price:.0f}, "
        f"mark-to-market {last_date} @ {last_close:.0f} = {mtm_pct:+.1f}%. "
        "Book counts this as a winner — it must at least be profitable."
    )


# ─────────────────────────────────────────────────────────────────────
# Asymmetric P&L — the book's CORE qualitative claim
# ─────────────────────────────────────────────────────────────────────

def test_asymmetry_validates_book_claim(trades) -> None:
    """The book's central claim: 손실 미미, 수익 훨씬 큼.

    Operationalized as avg_win / |avg_loss| > 2.0. Currently observed
    ratio is ~5.25 (avg_win 33.5% vs avg_loss 6.4%). Bound widely so
    natural data drift doesn't flake the test."""
    s = summarize(trades)
    assert s["asymmetry"] is not None, (
        "Need both wins and losses to compute asymmetry. If the open "
        "trade closed during fixture update, re-check the breakdown."
    )
    assert s["asymmetry"] > 2.0, (
        f"asymmetry = avg_win/|avg_loss| = {s['asymmetry']:.2f}. "
        "Book says 비대칭 손익 (loss small, win big). Below 2 invalidates "
        "the book's chapter thesis on Samsung."
    )


def test_worst_loss_is_small(trades) -> None:
    """Book: 손실 미미. The biggest single loss should not exceed 10%.
    Currently observed -6.4% (2021-12 → 2022-01)."""
    s = summarize(trades)
    assert s["worst_pct"] >= -10.0, (
        f"worst trade was {s['worst_pct']:.1f}%. Book says 손실 미미 — "
        "anything beyond -10% on a closed trade contradicts the book."
    )


def test_best_win_is_substantial(trades) -> None:
    """Book: 수익 훨씬 큼. The biggest single closed win should be
    ≥20% (book's chart visibly shows a large move from 2023-01 entry
    to 2024-08 exit)."""
    s = summarize(trades)
    assert s["best_pct"] >= 20.0, (
        f"best closed trade was {s['best_pct']:.1f}%. Book's chart shows "
        "much bigger moves than this — investigate."
    )
