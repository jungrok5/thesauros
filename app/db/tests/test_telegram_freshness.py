"""Unit tests for the telegram alert's freshness extraction logic.

Mirrors the TypeScript-side `pickFreshest()` test in
`web-next/src/lib/__tests__/freshness.test.ts`. Both sides MUST agree
on which pattern wins and what runup % it shows — otherwise a user
gets one number in the web app and a different one in the telegram
alert, eroding trust.

These tests do NOT hit the DB. They feed a synthetic analyze_results
blob into `_freshness_of()` directly.
"""
from typing import Optional

from app.db.telegram_worker import _freshness_of, _fresh_zone_label


def _pat(kind: str, direction: str, completed: bool, extra: Optional[dict]) -> dict:
    return {
        "kind": kind,
        "direction": direction,
        "completed": completed,
        "extra": extra,
    }


# ─────────────────────────────────────────────────────────────────────
# _freshness_of — picks the best fresh bullish pattern
# ─────────────────────────────────────────────────────────────────────

def test_returns_none_when_no_patterns():
    assert _freshness_of({"patterns": [], "last_close": 100}) is None


def test_returns_none_when_no_last_close():
    assert _freshness_of({"patterns": [_pat("쌍바닥", "bullish", True, {"neckline": 80})]}) is None


def test_picks_pattern_with_neckline_only():
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("쌍바닥", "bullish", True, {"neckline": 80}),
        ],
    }
    out = _freshness_of(blob)
    assert out is not None
    assert out["kind"] == "쌍바닥"
    assert abs(out["runup"] - 25.0) < 0.01


def test_skips_patterns_without_breakout_level():
    """삼중바닥 only stores `bottoms` in extra — no neckline / rim /
    ma_240 / ma_value. The function must skip those (we don't have a
    breakout reference to compute runup against)."""
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("삼중바닥", "bullish", True, {"bottoms": [{}]}),
        ],
    }
    assert _freshness_of(blob) is None


def test_skips_bearish_patterns():
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("쌍천장", "bearish", True, {"neckline": 80}),
        ],
    }
    assert _freshness_of(blob) is None


def test_skips_incomplete_patterns():
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("쌍바닥", "bullish", False, {"neckline": 80}),
        ],
    }
    assert _freshness_of(blob) is None


def test_prefers_freshest_when_multiple_bullish_patterns():
    """국보디자인 + SK텔레콤 pattern stack: fresh ~3% rises above stale +70%."""
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("역H&S", "bullish", True, {"neckline": 60}),    # +67%
            _pat("쌍바닥", "bullish", True, {"neckline": 97}),    # +3%
        ],
    }
    out = _freshness_of(blob)
    assert out["kind"] == "쌍바닥"
    assert abs(out["runup"] - 3.09) < 0.1


def test_picks_neckline_over_ma_240():
    """If both neckline and ma_240 are present, neckline wins (more specific)."""
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("쌍바닥", "bullish", True, {"neckline": 80, "ma_240": 50}),
        ],
    }
    out = _freshness_of(blob)
    # Expect 100/80 - 1 = 25%, not 100/50 - 1 = 100%
    assert abs(out["runup"] - 25.0) < 0.01


def test_falls_back_to_ma_240_when_no_neckline():
    blob = {
        "last_close": 100,
        "patterns": [
            _pat("240MA 돌파매매", "bullish", True, {"ma_240": 80}),
        ],
    }
    out = _freshness_of(blob)
    assert out["kind"] == "240MA 돌파매매"
    assert abs(out["runup"] - 25.0) < 0.01


# ─────────────────────────────────────────────────────────────────────
# _fresh_zone_label — Korean phrase by runup zone
# ─────────────────────────────────────────────────────────────────────

def test_zone_label_buckets():
    assert _fresh_zone_label(3) == "🟢 지금 진입 자리"
    assert _fresh_zone_label(12) == "추격 가능"
    assert _fresh_zone_label(20) == "일부 진입 자리 지남"
    assert _fresh_zone_label(70) == "⚠ 진입 자리 끝남"
    assert _fresh_zone_label(-5) == "풀백 검토"
    assert _fresh_zone_label(-25) == "🔴 무효 가능"


def test_zone_boundaries():
    """The 0%, 5%, 15%, 30% boundaries must hit the right bucket so the
    alert matches the FreshnessChip on the website."""
    assert _fresh_zone_label(0) == "🟢 지금 진입 자리"
    assert _fresh_zone_label(4.99) == "🟢 지금 진입 자리"
    assert _fresh_zone_label(5) == "추격 가능"
    assert _fresh_zone_label(14.99) == "추격 가능"
    assert _fresh_zone_label(15) == "일부 진입 자리 지남"
    assert _fresh_zone_label(29.99) == "일부 진입 자리 지남"
    assert _fresh_zone_label(30) == "⚠ 진입 자리 끝남"
