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


# ─────────────────────────────────────────────────────────────────────
# 4등분선 (book p218-223) — the book's signature mechanic
# ─────────────────────────────────────────────────────────────────────

def test_quarter_zone_safe75():
    """Current price ≥ 75 % up the bullish body → safe75 (책: 매수)."""
    from app.book.candles import quarter_zone
    # Bull bar 100 → 200 (body 100). 175 = 75 % up.
    assert quarter_zone(100, 200, 180) == "safe75"
    assert quarter_zone(100, 200, 220) == "safe75"
    assert quarter_zone(100, 200, 175) == "safe75"


def test_quarter_zone_warn50():
    from app.book.candles import quarter_zone
    assert quarter_zone(100, 200, 160) == "warn50"
    assert quarter_zone(100, 200, 150) == "warn50"


def test_quarter_zone_danger25_and_broken():
    from app.book.candles import quarter_zone
    assert quarter_zone(100, 200, 140) == "danger25"
    assert quarter_zone(100, 200, 125) == "danger25"
    # Below 25 % = 절대자리 깨짐
    assert quarter_zone(100, 200, 120) == "broken"
    assert quarter_zone(100, 200, 80) == "broken"


def test_quarter_zone_na_for_non_bullish_reference():
    """Bearish or zero-body reference returns n/a."""
    from app.book.candles import quarter_zone
    assert quarter_zone(200, 100, 150) == "n/a"
    assert quarter_zone(100, 100, 100) == "n/a"


# ─────────────────────────────────────────────────────────────────────
# 구라캔들 / 양팔봉 / 갭 (Phase 2 P2)
# ─────────────────────────────────────────────────────────────────────

def test_gura_candle_big_body_low_volume():
    """Big-bodied candle with vol < 0.7 × avg → 구라캔들 tag (book p214).
    Volume can't be faked, so a strong move on weak volume is suspect."""
    c = _c(open_v=100, close=88, high=100.3, low=87.8)   # body 92 % bearish
    tags = classify_candle(c, body_avg=2, vol_avg=10000)
    # candle.volume = 1000 (from _c helper) < 0.7 × 10000 = 7000 → 구라캔들
    assert "구라캔들" in tags


def test_yangpalbong_balanced_wicks():
    """Long upper AND lower wicks with small body → 양팔봉."""
    c = _c(open_v=100, close=100.5, high=104, low=96)
    # body 0.5, range 8, upper 3.5/8 = 44 %, lower 4/8 = 50 %, body 6 %
    tags = classify_candle(c, body_avg=2, vol_avg=1000)
    assert "양팔봉" in tags


def test_gap_up_detection():
    """O > 1.01 × prev_close → 갭상승."""
    c = _c(open_v=110, close=112, high=113, low=109.5)
    tags = classify_candle(c, body_avg=2, vol_avg=1000, prev_close=100.0)
    assert "갭상승" in tags


def test_gap_down_detection():
    c = _c(open_v=95, close=93, high=95.5, low=92)
    tags = classify_candle(c, body_avg=2, vol_avg=1000, prev_close=100.0)
    assert "갭하락" in tags


def test_gap_absent_when_no_prev_close():
    """First bar has no prior close → no gap tag should fire."""
    c = _c(open_v=100, close=102, high=103, low=99)
    tags = classify_candle(c, body_avg=2, vol_avg=1000, prev_close=None)
    assert not any(t in ("갭상승", "갭하락") for t in tags)
