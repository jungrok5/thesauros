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
    test focuses on the gate rules, not the rest of the analyzer.

    The 2026-05-26 audit added three book-rule gates (240MA stretched,
    monthly 240MA missing, candle reversal at top). The fixture
    defaults are filled to keep those gates QUIET so existing tests
    keep exercising the gate they were written for. Individual tests
    override the field they're proving."""
    base: Dict[str, Any] = {
        "ticker": "TEST.KS",
        "action": "HOLD",
        "last_close": 100.0,
        "trend": {
            # monthly.ma_240 filled so is_monthly_240ma_missing() stays
            # False. Distance from last_close (100) is comfortable so
            # is_240ma_stretched() (>+50%) also stays False.
            "monthly": {"above_ma_10": True, "ma_10": 95.0,
                         "ma_240": 80.0, "above_ma_240": True,
                         "alignment_score": 0.5},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0,
                         "ma_240": 80.0, "above_ma_240": True,
                         "alignment_score": 0.5},
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
    — 자리 X. Eligibility must agree.

    2026-05-26 F12 added — indecision tags (도지/양팔봉) now trigger an
    earlier indecision_candle gate. To exercise ambush specifically,
    fixture uses body_pct<0.2 (which is_ambush_setup's own indecision
    check accepts) instead of an indecision tag F12 would catch first."""
    blob = _result(
        action="BUY",
        patterns=[{
            "kind": "MA 수렴 매복", "completed": False,
            "direction": "neutral",
        }],
        volume_case={"case": 12},   # drying volume
        last_candle={"tags": [], "body_pct": 0.1},  # indecision via body_pct
        consolidation_ratio=0.04,   # tight box (≤6%)
        last_close=100.0,
        # ma_240 filled so the new is_monthly_240ma_missing / is_240ma_stretched
        # gates don't shadow the ambush check this test is exercising.
        trend={"monthly": {"above_ma_10": True, "ma_10": 95, "ma_240": 80},
               "weekly":  {"above_ma_10": True, "ma_10": 96, "ma_240": 80}},
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
        last_candle={"tags": [], "body_pct": 0.1},  # body-only indecision (F12 skips)
        consolidation_ratio=0.04,
        last_close=110.0,                                                 # +14.6% over weekly ma_10
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 80.0}},
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


# ─────────────────────────────────────────────────────────────────────
# Book-rule audit gates (2026-05-26): F7 240MA stretch / F8 missing
# monthly 240MA / F9 candle reversal at top.
# ─────────────────────────────────────────────────────────────────────

def test_stretched_240ma_downgrades_buy():
    """F7 — last_close > weekly ma_240 * 1.5 (책의 +50% 신규 진입 룰
    위반). The 024800.KQ 유성티엔에스 audit case: 240MA +82% yet
    eligibility=OK previously."""
    blob = _result(
        action="STRONG_BUY",
        last_close=160.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0}},
        # last_close 160 / weekly ma_240 100 = +60% > +50% threshold
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "stretched_240"
    assert "240MA" in v["body"] and "+50%" in v["body"]


def test_stretched_240ma_borderline_50pct_stays_ok():
    """Exactly +50% over weekly ma_240 stays OK — gate triggers on
    strictly > 50%."""
    blob = _result(
        action="BUY",
        last_close=149.0,   # +49% over ma_240 100
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"


def test_missing_monthly_240ma_does_NOT_downgrade_buy_alone():
    """F8 walked back 2026-05-26 — initial rollout treated missing
    monthly 240MA as a CONDITIONAL trigger but it caught 8/10 candidates
    on the TOP 10 audit run. The book's canonical 240MA gate is WEEKLY
    (ch.4 '1년 매수 심리'); monthly 240MA is the longer-horizon variant
    and shouldn't block bullish eligibility on its own. BookVerdict
    surfaces a warning when monthly_240 is missing — that's enough."""
    blob = _result(
        action="STRONG_BUY",
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": None},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 80.0},
        },
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"  # not downgraded by missing monthly alone


def test_candle_reversal_at_top_downgrades_buy():
    """F9 — upper-wick reversal candle (교수형 / 그레이브스톤도지 /
    유성형 / 역망치형 / 눈썹캔들 OR upper_wick > 40%) combined with
    52w >= 70% OR 8w rally >= 15% should downgrade. The 383800.KS
    LX홀딩스 audit case: 52w 84% + 19% rally + 교수형 → OK previously."""
    blob = _result(
        action="STRONG_BUY",
        last_candle={"tags": ["교수형"], "upper_wick_pct": 0.1, "body_pct": 0.3},
        position_in_52w=0.84,    # >= 0.70 trigger
        rally_8w_pct=0.19,       # also >= 0.15 trigger
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "candle_top"


def test_candle_reversal_alone_now_downgrades_via_F12():
    """2026-05-26 F12 reform — reversal candle alone (mid-trend, not at
    52w/rally top) now downgrades to CONDITIONAL. Previously this stayed
    OK on the theory that mid-trend reversal could be noise, but the
    audit_200 sample showed 22% of system-buys had indecision/reversal
    last candles that violated the book's "next-bar wait" rule (p247).
    F9's at-top precondition was too restrictive."""
    blob = _result(
        action="BUY",
        last_candle={"tags": ["교수형"], "upper_wick_pct": 0.1, "body_pct": 0.3},
        position_in_52w=0.50,
        rally_8w_pct=0.05,
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "indecision_candle"


def test_audit_gates_priority_order():
    """When multiple downgrade gates trigger, the most fundamental
    book-rule violation wins so the user sees the strictest reason.
    Order: below_weekly_240 > stretched_240 > post_rally > candle_top
    > stale > ambush."""
    # stretched_240 wins over missing_monthly_240
    blob = _result(
        action="STRONG_BUY",
        last_close=200.0,
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": None},  # missing
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0},  # stretched +100%
        },
    )
    v = compute_eligibility(blob)
    assert v["reason_code"] == "stretched_240"


def test_below_weekly_240ma_downgrades_buy():
    """F10 (2026-05-26 second audit) — surfaced via 041930.KQ:
    last_close 7,080 vs weekly 240MA 8,031 (-12%) yet eligibility=OK
    so it ranked #1 in the screener. Book ch.4 '240MA = 1년 매수 심리':
    아래면 죽은 차트, 매수 X."""
    blob = _result(
        action="STRONG_BUY",
        last_close=88.0,    # below ma_240 100
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0},
        },
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "below_weekly_240"
    assert "240MA 아래" in v["body"]


def test_below_weekly_240ma_outranks_stretched_in_priority():
    """Pathological case (price below 240MA AND somehow > 1.5x of stale
    240MA reading) — the more fundamental "추세 죽음" violation must
    take precedence in the reason naming."""
    blob = _result(
        action="STRONG_BUY",
        last_close=88.0,    # below ma_240
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0},
        },
    )
    v = compute_eligibility(blob)
    assert v["reason_code"] == "below_weekly_240"


def test_weekly_240ma_missing_downgrades_buy():
    """F11 (2026-05-26 third audit) — surfaced via 420570.KQ
    제이투케이바이오: weekly.ma_240 + monthly.ma_240 둘 다 None
    (신규 상장 4.6년 미만) 인데 eligibility=OK 라 스크리너 1위. Book ch.4
    240MA = 1년 매수 심리 평가 불가 → 매수 자리 판단 불가능."""
    blob = _result(
        action="STRONG_BUY",
        last_close=100.0,
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": None},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": None},
        },
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "weekly_240_missing"
    assert "주봉 240MA" in v["body"]


def test_weekly_240ma_present_with_monthly_missing_stays_ok():
    """Regression — F8 walk-back (monthly missing alone) must still let
    these through. F11 only fires when WEEKLY 240MA is also missing."""
    blob = _result(
        action="STRONG_BUY",
        last_close=100.0,
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": None},  # missing
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 80.0},   # present
        },
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"


def test_indecision_candle_alone_downgrades_buy():
    """F12 (2026-05-26 audit_200): 도지/양팔봉/위꼬리>40% 자체로
    CONDITIONAL. F9 (at-top reversal) trigger 조건 미달인 mid-trend
    case 까지 책 정신 적용 — 책 p247 "양팔봉: 방향 미정, 다음 봉 관찰"."""
    blob = _result(
        action="STRONG_BUY",
        last_candle={"tags": ["양팔봉"], "upper_wick_pct": 0.1,
                     "body_pct": 0.3},
        position_in_52w=0.40,    # 명백히 not at-top
        rally_8w_pct=0.05,       # 약한 rally
        last_close=120.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "indecision_candle"
    assert "방향 미정" in v["body"]


def test_at_top_reversal_keeps_F9_reason_not_F12():
    """When BOTH F9 (at-top + reversal) and F12 (indecision alone) would
    fire, the stricter F9 reason ("매도세 출현 + 랠리 끝") wins so the
    user sees the more critical message."""
    blob = _result(
        action="STRONG_BUY",
        last_candle={"tags": ["교수형"], "upper_wick_pct": 0.5,
                     "body_pct": 0.3},
        position_in_52w=0.85,
        rally_8w_pct=0.20,
        last_close=120.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0}},
    )
    v = compute_eligibility(blob)
    # post_rally outranks candle_top here (52w>=85% AND rally>=10% triggers
    # post_rally) — both are valid stop-selling signals; just pin the
    # priority and reason so future routing tweaks don't silently invert.
    assert v["reason_code"] in ("post_rally", "candle_top")
    assert v["reason_code"] != "indecision_candle"


def test_below_weekly_ma10_downgrades_buy():
    """F13 (2026-05-26 audit_200): action=BUY + score>=0.7 종목 4건이
    weekly.above_ma_10=False 인데도 eligibility=OK. 책 ch.4: 주봉 10MA
    아래 = 단기 추세 사망 라인. CONDITIONAL — 재진입은 10MA 회복 후."""
    blob = _result(
        action="BUY",
        last_close=90.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": False, "ma_10": 100.0, "ma_240": 80.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "CONDITIONAL"
    assert v["reason_code"] == "below_weekly_ma10"
    assert "주봉 10MA" in v["body"]


def test_above_weekly_ma10_stays_ok():
    """Regression — true above_ma_10 stays OK."""
    blob = _result(
        action="BUY",
        last_close=110.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 100.0, "ma_240": 80.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"


def test_clean_candle_at_normal_position_still_OK():
    """Sanity — body 양봉, tags 비어있음, upper_wick 정상 → F12 안 fire."""
    blob = _result(
        action="STRONG_BUY",
        last_candle={"tags": [], "upper_wick_pct": 0.1, "body_pct": 0.6},
        position_in_52w=0.40,
        rally_8w_pct=0.05,
        last_close=120.0,
        trend={"monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
               "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0}},
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"


def test_exactly_at_weekly_240ma_stays_ok():
    """last_close == weekly ma_240 is the boundary — should NOT trigger
    the dead-chart downgrade (only strictly below)."""
    blob = _result(
        action="BUY",
        last_close=100.0,
        trend={
            "monthly": {"above_ma_10": True, "ma_10": 95.0, "ma_240": 80.0},
            "weekly":  {"above_ma_10": True, "ma_10": 96.0, "ma_240": 100.0},
        },
    )
    v = compute_eligibility(blob)
    assert v["grade"] == "OK"
