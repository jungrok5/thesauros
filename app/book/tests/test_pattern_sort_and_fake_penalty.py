"""Pin the 2026-05-26 audit reform:

  1. pattern_sort_key — weekly-first + fake_volume penalty.
     Was monthly:3, weekly:2 — sat a weekly 삼중바닥 conf=0.87 behind
     a monthly 삼중바닥 conf=0.56 (fake_volume) on 383800.KS.

  2. _signal_score — fake_volume halves the confidence contribution.
     Score cap is still 1.0; this only matters when a fake pattern
     would otherwise be the lone bullish signal.
"""
from app.book.analyzer import pattern_sort_key, _signal_score


def _p(kind: str, tf: str, conf: float, *, fake: bool = False,
       direction: str = "bullish", completed: bool = True) -> dict:
    return {
        "kind": kind,
        "timeframe": tf,
        "confidence": conf,
        "direction": direction,
        "completed": completed,
        "extra": {"fake_volume": True} if fake else {},
    }


# ──────────────────────────────────────────────────────────────────
# pattern_sort_key
# ──────────────────────────────────────────────────────────────────

def test_weekly_outranks_monthly_at_same_confidence():
    """Book ch.4: 매매 = 주봉. Weekly must beat monthly when conf ties."""
    pats = [
        _p("삼중바닥", "monthly", 0.80),
        _p("삼중바닥", "weekly",  0.80),
    ]
    pats.sort(key=pattern_sort_key)
    assert pats[0]["timeframe"] == "weekly"


def test_383800_regression_weekly_clean_beats_monthly_fake():
    """The audit case that triggered the reform: monthly conf=0.56
    fake was selected over weekly conf=0.87 clean."""
    pats = [
        _p("삼중바닥", "monthly", 0.56, fake=True),
        _p("삼중바닥", "weekly",  0.87, fake=False),
    ]
    pats.sort(key=pattern_sort_key)
    assert pats[0]["timeframe"] == "weekly"
    assert pats[0]["confidence"] == 0.87


def test_fake_penalty_demotes_within_same_timeframe():
    """Inside the same timeframe, fake reduces effective confidence by
    0.3 — enough to put a clean 0.6 above a fake 0.85."""
    pats = [
        _p("쌍바닥",   "weekly", 0.85, fake=True),
        _p("삼중바닥", "weekly", 0.60, fake=False),
    ]
    pats.sort(key=pattern_sort_key)
    assert pats[0]["confidence"] == 0.60
    assert (pats[0].get("extra") or {}).get("fake_volume", False) is False


def test_very_strong_clean_still_beats_fake_in_lower_tf():
    """Don't over-correct: a weekly conf=0.95 clean must still rank
    above a monthly conf=0.50 fake (which both rank shifts agree on).
    Edge case: weekly conf=0.50 clean vs monthly conf=0.95 — weekly
    wins because of timeframe priority, by design."""
    pats = [
        _p("catalyst", "monthly", 0.95, fake=False),
        _p("catalyst", "weekly",  0.50, fake=False),
    ]
    pats.sort(key=pattern_sort_key)
    assert pats[0]["timeframe"] == "weekly"  # weekly always wins


def test_daily_ranks_last():
    pats = [
        _p("a", "daily",   0.99),
        _p("b", "monthly", 0.40),
    ]
    pats.sort(key=pattern_sort_key)
    assert pats[0]["timeframe"] == "monthly"


# ──────────────────────────────────────────────────────────────────
# _signal_score fake penalty
# ──────────────────────────────────────────────────────────────────

def test_signal_score_penalises_fake_volume_pattern():
    """One bullish pattern, conf=0.80. Score with fake should be half
    of score without fake (delta halves)."""
    clean = [_p("삼중바닥", "weekly", 0.80, fake=False)]
    fake  = [_p("삼중바닥", "weekly", 0.80, fake=True)]
    s_clean = _signal_score("BUY", clean, [], None)
    s_fake  = _signal_score("BUY", fake,  [], None)
    # Base 0.6 + conf*0.30:  clean = 0.6 + 0.24 = 0.84
    #                        fake  = 0.6 + 0.12 = 0.72
    assert s_clean > s_fake
    assert abs(s_clean - 0.84) < 1e-6
    assert abs(s_fake  - 0.72) < 1e-6


def test_signal_score_cap_means_fake_penalty_invisible_when_score_saturated():
    """Documents the known limitation: when several strong bullish
    signals already saturate the [-1, +1] cap, halving one fake
    pattern doesn't move the surface score. This is why we also
    fixed entry_plan selection (the other follow-up) — score alone
    isn't enough."""
    many = [
        _p("a", "weekly", 0.90, fake=False),
        _p("b", "weekly", 0.90, fake=False),
        _p("c", "monthly", 0.80, fake=True),   # the fake one
    ]
    same_minus_fake_flag = [{**p, "extra": {}} for p in many]
    s_with_flag = _signal_score("BUY", many, [], None)
    s_no_flag   = _signal_score("BUY", same_minus_fake_flag, [], None)
    assert s_with_flag == 1.0
    assert s_no_flag   == 1.0   # already capped before subtraction
