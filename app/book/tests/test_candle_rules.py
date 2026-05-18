"""Candle classification rules — keeps the tag set consistent with what
the book teaches (도지 / 망치 / 역망치 / 눈썹 / 장대양봉 etc.).

Regression suite for the 국보디자인 2026-05-22 case: a candle with
body 14 %, lower wick 68 %, upper wick 18 % was returning `tags = []`
because the old 망치 rule required upper-wick < 0.15. That made the
analyzer miss the "lower-wick rejection" signal entirely.
"""
from __future__ import annotations

from app.book.candles import classify_candle, CandleParts


def _c(open_v: float, close: float, high: float, low: float) -> CandleParts:
    """Build a CandleParts via from_row so we don't have to track every
    field the dataclass adds (close_position, etc.)."""
    return CandleParts.from_row({
        "open": open_v, "high": high, "low": low, "close": close, "volume": 1000,
    })


def test_gukbo_2026_05_22_long_lower_wick():
    """O=24,600  H=24,800  L=23,700  C=24,450 → body 14%, lower 68%,
    upper 18%. This should be a clear 교수형 (bearish hammer-equivalent)
    — used to return tags=[] under the old strict rule."""
    c = _c(open_v=24600, close=24450, high=24800, low=23700)
    tags = classify_candle(c, body_avg=200, vol_avg=50000)
    assert "교수형" in tags, f"expected 교수형, got {tags}"


def test_textbook_hammer_bullish():
    """Long lower wick, small body, no upper wick — classic 망치형."""
    c = _c(open_v=100, close=102, high=103, low=92)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "망치형" in tags, tags


def test_textbook_inverted_hammer():
    """Long upper wick, small body, no lower wick."""
    c = _c(open_v=100, close=98, high=108, low=97)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "유성형" in tags, tags


def test_doji_zero_body():
    """Body 1 %, both wicks present → 도지."""
    c = _c(open_v=100, close=100.05, high=102, low=98)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert any("도지" in t for t in tags), tags


def test_near_doji_below_widened_threshold():
    """Body 11 % → just below the new 12 % cutoff, should still tag 도지."""
    c = _c(open_v=100, close=100.4, high=102, low=98.5)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    # body = 0.4, range = 3.5, body_pct = 11.4 % → under 12 → 도지
    assert any("도지" in t for t in tags), tags


def test_spinning_top_eyebrow():
    """Small body, both wicks 20-40 % each — 눈썹캔들."""
    c = _c(open_v=100, close=101, high=104, low=97)
    # body 1, upper 3, lower 3, range 7 → body 14 %, upper 43 %, lower 43 %
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    # Symmetric wicks not biased to one side → 눈썹캔들 expected.
    assert "눈썹캔들" in tags, tags


def test_long_bullish_body_jangdae_yangbong():
    c = _c(open_v=100, close=110, high=110.5, low=99.8)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "장대양봉" in tags, tags


def test_long_bearish_body_jangdae_eumbong():
    c = _c(open_v=110, close=100, high=110.2, low=99.5)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "장대음봉" in tags, tags


def test_asymmetric_wick_takes_priority_over_eyebrow():
    """Modest body, lower wick 3× upper wick → 망치형, NOT 눈썹."""
    # body 2, upper 0.5, lower 7.5, range 10 → body 20 %, lower 75 %, upper 5 %
    c = _c(open_v=100, close=102, high=102.5, low=92.5)
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "망치형" in tags, tags
    assert "눈썹캔들" not in tags, "asymmetric candle should not also tag 눈썹"
