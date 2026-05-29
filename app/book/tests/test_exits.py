"""Pure-function unit tests for app/book/exits.py.

These pin the book engine's 장대양봉 / 4등분 25% / 월봉 10MA semantics
so portfolio_book (backtest) and notify_book_exits (alerter) can rely
on a single source of truth. If anyone tries to "tune" the multipliers
or thresholds without explicit walk-forward proof, these tests are
the brake.
"""
from __future__ import annotations

from app.book.exits import (
    LONG_BULLISH_BODY_MULT, MONTHLY_MA_WINDOW,
    is_jangdae_yangbong,
    quartile_25_level,
    monthly_10ma_broken,
)


class TestJangdaeYangbong:
    def test_body_two_times_average_is_jangdae(self):
        # body = 20, avg body = 10 → ratio 2.0 (right at threshold)
        assert is_jangdae_yangbong(open_=100, close=120, recent_avg_body=10)

    def test_body_just_below_two_times_is_not(self):
        assert not is_jangdae_yangbong(open_=100, close=119, recent_avg_body=10)

    def test_bearish_bar_never_qualifies(self):
        assert not is_jangdae_yangbong(open_=120, close=100, recent_avg_body=10)

    def test_zero_avg_body_returns_false(self):
        # No volatility context → can't classify (book engine convention).
        assert not is_jangdae_yangbong(open_=100, close=200, recent_avg_body=0)

    def test_default_multiplier_pinned_at_two(self):
        # Catches anyone bumping LONG_BULLISH_BODY_MULT without auditing.
        assert LONG_BULLISH_BODY_MULT == 2.0


class TestQuartile25Level:
    def test_25pct_retracement_on_simple_body(self):
        # open=100, close=200, body=100, q25 = 100 + 25 = 125
        assert quartile_25_level(open_=100, close=200) == 125.0

    def test_zero_body_returns_open(self):
        assert quartile_25_level(open_=100, close=100) == 100.0


class TestMonthly10MABroken:
    def test_below_10ma_returns_true(self):
        closes = [100] * 9 + [50]   # 10-month MA = 95, latest 50 → broken
        assert monthly_10ma_broken(closes)

    def test_at_10ma_is_not_broken(self):
        # 10-month MA = 100, latest = 100 → NOT strictly below.
        assert not monthly_10ma_broken([100] * 10)

    def test_above_10ma_returns_false(self):
        closes = [80] * 9 + [120]
        assert not monthly_10ma_broken(closes)

    def test_insufficient_history_returns_false(self):
        # Newly listed (< 10 months) → no MA defined yet.
        assert not monthly_10ma_broken([100, 110, 120])

    def test_default_window_pinned_at_10(self):
        assert MONTHLY_MA_WINDOW == 10
