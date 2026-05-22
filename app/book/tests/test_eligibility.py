"""Tests for the Python buy-eligibility port.

Background: cron sent jungrok5 a "🟢 진입 신호 TSLA" while the
stock-detail NoviceVerdict card said "⚠️ 매수 자격: 조건부 — 지금은 자리
X". The page used a TypeScript derivation; the telegram worker had no
equivalent. `app/book/eligibility.py` is the Python port that closes
that gap — these tests pin it against the TS rules so a drift between
the two stays catchable.

Test categories:
  1. Direct action → verdict mapping (BUY/HOLD/AVOID/SELL/etc.)
  2. Bullish-action DOWNGRADE gates (ambush / stale / post-rally)
  3. Reaper recognition inside SELL branches
  4. Stretch-hold variant of HOLD
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.book.eligibility import (
    compute_eligibility,
    is_ambush_setup,
    is_post_rally_caution,
)


# ─────────────────────────────────────────────────────────────────────
# Fixture builder
# ─────────────────────────────────────────────────────────────────────

def _result(**overrides) -> Dict[str, Any]:
    """Minimal analyze_ticker output blob — fields downstream of
    eligibility.compute_eligibility are intentionally absent so the
    test focuses on the gate rules, not the rest of the analyzer."""
    base: Dict[str, Any] = {
        "ticker": "TEST.KS",
        "action": "HOLD",
        "last_close": 100.0,
        "trend": {
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "alignment_score": 0.5},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "alignment_score": 0.5},
        },
        "patterns": [],
        "volume_case": {"case": 0},
        "last_candle": {"tags": [], "upper_wick_pct": 0.0, "body_pct": 0.5},
        "consolidation_ratio": 0.2,
        "position_in_52w": 0.5,
        "rally_8w_pct": 0.0,
        "stretch_reason": None,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────
# 1. Direct action → verdict mapping
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("action,expected_grade,headline_fragment", [
    ("STRONG_BUY", "OK",       "강한 매수"),
    ("BUY",        "OK",       "가능 (매수)"),
    ("HOLD",       "WATCH",    "관망"),
    ("AVOID",      "AVOID",    "회피"),
    ("SELL",       "EXIT",     "매도 신호"),
])
def test_basic_action_mapping(action, expected_grade, headline_fragment):
    v = compute_eligibility(_result(action=action))
    assert v["grade"] == expected_grade
    assert headline_fragment in v["headline"], v


def test_unknown_action_falls_back_to_watch():
    v = compute_eligibility(_result(action="MYSTERY"))
    assert v["grade"] == "WATCH"


# ─────────────────────────────────────────────────────────────────────
# 2. Ambush downgrade — the gate that bit on TSLA
# ─────────────────────────────────────────────────────────────────────

def test_ambush_downgrades_buy_to_conditional():
    """The reported TSLA case: action=BUY, but ≥2 of {수렴 매복 pattern,
    drying volume, indecision candle, tight box} → page says CONDITIONAL
    — 자리 X. Eligibility must agree."""
    blob = _result(
        action="BUY",
        patterns=[{
            "kind": "MA 수렴 매복", "completed": False,
            "direction": "neutral",
        }],
        volume_case={"case": 12},   # drying volume
        last_candle={"tags": ["도지"], "body_pct": 0.1},  # indecision
        consolidation_ratio=0.04,   # tight box (≤6%)
        last_close=100.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95},
               "weekly":  {"above_ma_10": True, "ma_10": 96}},  # last_close not >5% above ma_10w
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL", v
    assert v["reason_code"] == "ambush"
    assert "지금은 자리 X" in v["headline"]


def test_ambush_disqualified_when_price_already_5pct_above_ma10w():
    """If price has cleared 주봉 10MA by >5%, the porting trigger has
    effectively fired — not still pending. Ambush should NOT apply."""
    blob = _result(
        action="BUY",
        patterns=[{"kind": "MA 수렴 매복", "completed": False, "direction": "neutral"}],
        volume_case={"case": 12},
        last_candle={"tags": ["도지"], "body_pct": 0.1},
        consolidation_ratio=0.04,
        last_close=110.0,                                                 # +14.6% over weekly ma_10
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK", v  # ambush gate didn't fire → normal BUY


def test_ambush_disqualified_at_52w_high():
    """≥85% of 52w range is post-rally territory, not pre-breakout
    accumulation. Ambush gate must skip."""
    blob = _result(
        action="BUY",
        patterns=[{"kind": "MA 수렴 매복", "completed": False, "direction": "neutral"}],
        volume_case={"case": 12},
        consolidation_ratio=0.04,
        position_in_52w=0.92,
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"  # ambush skipped; falls into BUY branch


def test_ambush_requires_at_least_two_signals():
    """One hit alone (e.g. tight box only) is not enough to flip a BUY."""
    blob = _result(
        action="BUY",
        consolidation_ratio=0.04,   # only tight box, nothing else
    )
    assert not is_ambush_setup(blob)
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"


# ─────────────────────────────────────────────────────────────────────
# 3. Stale-pattern downgrade
# ─────────────────────────────────────────────────────────────────────

def test_stale_pattern_downgrades_buy():
    """If the freshest bullish pattern has runup > 30% past breakout,
    the entry is long past. Page says 'CONDITIONAL — 자리 X'."""
    blob = _result(
        action="BUY",
        patterns=[{
            "kind": "쌍바닥", "completed": True, "direction": "bullish",
            "extra": {"neckline": 70.0},
        }],
        last_close=100.0,  # +43% over breakout
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "stale"


def test_pattern_below_breakout_is_NOT_stale():
    """Below-breakout = invalidation territory, not stale entry. Should
    NOT trigger downgrade; the action's own gates handle it."""
    blob = _result(
        action="BUY",
        patterns=[{
            "kind": "쌍바닥", "completed": True, "direction": "bullish",
            "extra": {"neckline": 110.0},
        }],
        last_close=100.0,  # below breakout → invalidation, not stale
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"  # no downgrade


# ─────────────────────────────────────────────────────────────────────
# 4. Post-rally caution downgrade
# ─────────────────────────────────────────────────────────────────────

def test_post_rally_caution_downgrades_buy():
    blob = _result(
        action="BUY",
        position_in_52w=0.92,
        rally_8w_pct=0.30,
        last_candle={"tags": ["유성형"], "upper_wick_pct": 0.6, "body_pct": 0.2},
    )
    assert is_post_rally_caution(blob) is True
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "post_rally"


# ─────────────────────────────────────────────────────────────────────
# 5. Stretch-hold variant of HOLD
# ─────────────────────────────────────────────────────────────────────

def test_hold_with_stretch_reason_is_conditional():
    blob = _result(action="HOLD", stretch_reason="가격이 240MA 대비 80% 위 — 자리 지남")
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "stretch_hold"
    assert "자리 지남" in v["headline"]


def test_hold_without_stretch_is_watch():
    v = compute_eligibility(_result(action="HOLD"))
    assert v["grade"] == "WATCH"
    assert "관망" in v["headline"]


# ─────────────────────────────────────────────────────────────────────
# 6. Reaper recognition (저승사자 캔들)
# ─────────────────────────────────────────────────────────────────────

def test_reaper_sell_uses_dedicated_headline():
    blob = _result(
        action="SELL",
        stretch_reason="저승사자 캔들 — 장대음봉 + 주봉 10MA 동시 이탈",
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "EXIT"
    assert v["reason_code"] == "reaper"
    assert "저승사자" in v["headline"]


def test_reaper_only_applies_to_sell_branches():
    """저승사자 stretch_reason on a BUY action shouldn't reroute to the
    reaper verdict — the SELL gate is what makes it 저승사자 in the
    book sense. We respect the action label."""
    blob = _result(
        action="BUY",
        stretch_reason="저승사자 캔들 — 장대음봉",  # unusual combination
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"  # BUY mapping, not reaper rerouted
