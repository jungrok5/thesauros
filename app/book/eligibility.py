"""Single source of truth for the 'today's buy eligibility' verdict.

Background: the stock-detail page renders a `<NoviceVerdict>` card
("오늘 매수 자격: ...") in `web-next/src/components/analysis-view.tsx`
that downgrades the analyzer's raw `action` whenever it would conflict
with a book-spirit guard (ambush setup / stale pattern / post-rally
caution / stretch_reason / reaper candle). Before this module, that
logic lived ONLY in TypeScript and the telegram_worker had no way to
read it — so cron alerts could announce "🟢 진입 신호" for a ticker the
page was simultaneously flagging "⚠️ 매수 자격: 조건부 — 지금은 자리 X".

This module is the canonical Python port. `compute_eligibility()`
takes the full `analyze_ticker()` result blob and returns the same
verdict structure NoviceVerdict produces. The analyzer calls this at
the end of `analyze_ticker()` so the verdict ships inside
`analyze_results.result.eligibility` — telegram_worker reads from
there, and a TS parity check (`web-next/src/__tests__/eligibility-parity*`)
keeps the two derivations from drifting.

Verdict grades (alert-gating semantics):
  OK            매수 가능 — telegram emits enter alert
  CONDITIONAL   조건부 — telegram skips enter, may still emit pyramid/etc.
                with the ⚠️ prefix
  WATCH         관망 / HOLD — no enter alert
  AVOID         회피 — no enter alert ever
  EXIT          청산 신호 — exit alert flows unchanged
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Public — caller checks this to decide whether to send an "enter" class
# alert (enter / pyramid / target). Exit-class alerts (exit / stop /
# warn) are unaffected — they should fire regardless of buy eligibility.
ELIGIBLE_FOR_ENTER = {"OK"}


def _breakout_level(pattern: Dict[str, Any]) -> Optional[float]:
    """Mirrors `breakoutLevel()` in book-verdict.tsx — the price level
    that defines 'pattern broken out' for runup calculation. Patterns
    without one of these fields can't be evaluated for freshness."""
    extra = pattern.get("extra") or {}
    for key in ("neckline", "rim", "ma_240", "ma_value"):
        v = extra.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _pick_fresh_bullish_pattern(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mirror of `pickFreshBullishPattern()`. Returns the pattern whose
    runup-vs-breakout is smallest (most recent entry) or None.

    Skips patterns where price has fallen back BELOW breakout (runup<0)
    — those are pattern-invalidation, not fresh entries.
    """
    last = result.get("last_close")
    if not isinstance(last, (int, float)) or last <= 0:
        return None
    best: Optional[Dict[str, Any]] = None
    best_runup: Optional[float] = None
    for p in result.get("patterns") or []:
        if not p.get("completed"):
            continue
        if p.get("direction") != "bullish":
            continue
        bl = _breakout_level(p)
        if bl is None:
            continue
        runup = (last / bl - 1.0) * 100.0
        if runup < 0:
            continue
        if best is None or runup < best_runup:  # type: ignore[operator]
            best = {"kind": p.get("kind"), "breakout": bl, "runup_pct": runup}
            best_runup = runup
    return best


def is_240ma_stretched(result: Dict[str, Any]) -> bool:
    """주봉 240MA 대비 last_close 가 +50% 초과면 책의 '신규 진입 영역
    (+50% 이내)' 명백 위반. F7 (2026-05-26 audit) — TOP-10 manual
    review surfaced 024800.KQ 유성티엔에스: 240MA +82%인데 eligibility=OK.
    Post-rally caution gate already had a 52w >= 85% trigger but doesn't
    fire when price ran far from 240MA without quite reaching 52w high
    (mid-cap small-float plays). This gate catches the stretch directly."""
    weekly = (result.get("trend") or {}).get("weekly") or {}
    ma240 = weekly.get("ma_240")
    last = result.get("last_close")
    if not (isinstance(ma240, (int, float)) and ma240 > 0):
        return False
    if not isinstance(last, (int, float)) or last <= 0:
        return False
    return last > ma240 * 1.5


def is_below_weekly_240ma(result: Dict[str, Any]) -> bool:
    """주봉 240MA 아래 = 책의 가장 본질적인 매수 룰 위반.
    F10 (2026-05-26 second audit) — surfaced via 041930.KQ (SY동아):
    last_close 7,080 vs weekly 240MA 8,031 (-12%), BookVerdict 페이지가
    "주봉 240MA 아래 -12% — 책 기준 죽은 차트 영역" 명시하는데도
    eligibility=OK 라서 sortByBookSpirit 1위로 올라왔음.

    Book ch.4 "240MA = 1년 매수 심리": 240MA 위에서만 매수 검토.
    아래면 추세 살아있지 않음. 이건 stretched 보다도 본질적인 위반이라
    stretched/post-rally/candle-top 보다 먼저 평가."""
    weekly = (result.get("trend") or {}).get("weekly") or {}
    ma240 = weekly.get("ma_240")
    last = result.get("last_close")
    if not (isinstance(ma240, (int, float)) and ma240 > 0):
        return False  # 240MA 미계산은 별도 missing_monthly_240 게이트가 다룸
    if not isinstance(last, (int, float)) or last <= 0:
        return False
    return last < ma240


def is_monthly_240ma_missing(result: Dict[str, Any]) -> bool:
    """월봉 240MA 미계산 (신규 상장 / 20년 데이터 부재). Returns True iff
    the monthly 240MA can't be computed.

    2026-05-26 F8 (initial) treated this as a CONDITIONAL trigger on the
    theory that monthly 240MA was a load-bearing safety gate. A trigger
    run against the TOP 10 immediately showed the rule was over-strict:
    8 of 10 candidates were downgraded for this reason alone, and the
    book actually defines '240MA = 1년 매수 심리' against the WEEKLY
    240MA (book ch.4) — monthly 240MA is the longer-horizon variant,
    not the canonical safety gate.

    Kept as a helper so BookVerdict can still surface a warning ("⚠️
    월봉 240MA 미계산 — 장기 차트 부족") on the page without blocking
    the verdict. compute_eligibility() no longer uses this for the
    CONDITIONAL routing — see commit message for rationale."""
    monthly = (result.get("trend") or {}).get("monthly") or {}
    return monthly.get("ma_240") is None


def is_candle_reversal_at_top(result: Dict[str, Any]) -> bool:
    """마지막 캔들이 반전 신호 (교수형 / 그레이브스톤도지 / 유성형 /
    역망치형 / 눈썹캔들 OR upper_wick > 40%) AND price is at-or-near
    rally top (52w_pos ≥ 70% OR 8w rally ≥ 15%). F9 (2026-05-26 audit) —
    upper-wick reversal alone is too weak to downgrade (could be noise),
    but combined with a stretched price = book's 매도세 출현 신호.
    Distinct from is_post_rally_caution which needs the harder 52w ≥ 85%
    threshold — this catches borderline post-rally where caution is due
    but stricter gate doesn't fire."""
    lc = result.get("last_candle") or {}
    tags = lc.get("tags") or []
    upper_wick = lc.get("upper_wick_pct")
    REVERSAL_TAGS = {
        "교수형", "그레이브스톤도지", "유성형", "역망치형", "눈썹캔들",
    }
    has_reversal = (
        any(t in REVERSAL_TAGS for t in tags)
        or (isinstance(upper_wick, (int, float)) and upper_wick > 0.4)
    )
    if not has_reversal:
        return False
    pos = result.get("position_in_52w")
    rally = result.get("rally_8w_pct")
    near_top = isinstance(pos, (int, float)) and pos >= 0.7
    fast_rally = isinstance(rally, (int, float)) and rally >= 0.15
    return near_top or fast_rally


def is_post_rally_caution(result: Dict[str, Any]) -> bool:
    """Mirror of `isPostRallyCaution()`. True when at 52w high AND last
    8 weeks +10%+ AND last candle is upper-wick rejection OR price is
    in a tight box."""
    pos = result.get("position_in_52w")
    rally = result.get("rally_8w_pct")
    if not isinstance(pos, (int, float)) or pos < 0.85:
        return False
    if not isinstance(rally, (int, float)) or rally < 0.10:
        return False
    lc = result.get("last_candle") or {}
    tags: List[str] = lc.get("tags") or []
    upper_wick_pct = lc.get("upper_wick_pct")
    upper_wick_reversal = (
        "그레이브스톤도지" in tags
        or "유성형" in tags
        or "역망치형" in tags
        or (isinstance(upper_wick_pct, (int, float)) and upper_wick_pct > 0.5)
    )
    cons = result.get("consolidation_ratio")
    tight_box = isinstance(cons, (int, float)) and cons <= 0.06
    return bool(upper_wick_reversal or tight_box)


def is_ambush_setup(result: Dict[str, Any]) -> bool:
    """Mirror of `isAmbushSetup()`. 매복 = ≥2 of {수렴 매복 pattern,
    drying volume, indecision candle, tight box} AND not already
    cleared 주봉 10MA by >5% AND not at 52w high."""
    pos = result.get("position_in_52w")
    if isinstance(pos, (int, float)) and pos >= 0.85:
        return False

    trend = result.get("trend") or {}
    weekly = trend.get("weekly") or {}
    ma10w = weekly.get("ma_10")
    last_close = result.get("last_close")
    if (
        isinstance(ma10w, (int, float)) and ma10w > 0
        and isinstance(last_close, (int, float))
        and last_close > ma10w * 1.05
    ):
        return False

    patterns = result.get("patterns") or []
    has_setup_pattern = any(
        isinstance(p.get("kind"), str) and "수렴 매복" in p["kind"]
        for p in patterns
    )

    vc = result.get("volume_case") or {}
    vc_case = vc.get("case")
    drying_volume = vc_case == 12 or vc_case == 7

    lc = result.get("last_candle") or {}
    tags = lc.get("tags") or []
    body_pct = lc.get("body_pct")
    INDECISION_TAGS = {
        "도지", "눈썹캔들", "망치형", "교수형", "역망치형", "유성형",
        "드래곤플라이도지", "그레이브스톤도지",
    }
    indecision_candle = (
        any(t in INDECISION_TAGS for t in tags)
        or (isinstance(body_pct, (int, float)) and body_pct < 0.2)
    )

    cons = result.get("consolidation_ratio")
    tight_box = isinstance(cons, (int, float)) and cons <= 0.06

    hits = sum(1 for h in (has_setup_pattern, drying_volume,
                            indecision_candle, tight_box) if h)
    return hits >= 2


def _is_reaper(result: Dict[str, Any]) -> bool:
    """저승사자 = 장대음봉 동시 주봉 10MA 이탈. The analyzer stamps
    this in `stretch_reason` when the gate fires."""
    sr = result.get("stretch_reason")
    return isinstance(sr, str) and "저승사자" in sr


def compute_eligibility(result: Dict[str, Any]) -> Dict[str, Any]:
    """The canonical buy-eligibility verdict for a ticker.

    Mirrors `NoviceVerdict` in `web-next/src/components/analysis-view.tsx`
    1:1. Any divergence is a bug — kept honest by
    `web-next/src/__tests__/eligibility-parity.test.ts`.

    Returns a dict with:
      grade        — one of {OK, CONDITIONAL, WATCH, AVOID, EXIT}
      headline     — "오늘 매수 자격: …" — the page card's bold line
      body         — supporting sentence
      icon         — emoji used on the page card
      reason_code  — internal tag for downstream gating (None when not
                      a downgrade case)
    """
    action = result.get("action")
    bullish_action = action in ("BUY", "STRONG_BUY")

    # 1) Bullish-action downgrade gates (page calls these first).
    if bullish_action:
        fresh = _pick_fresh_bullish_pattern(result)
        stale_pattern = fresh is not None and fresh["runup_pct"] > 30
        post_rally = is_post_rally_caution(result)
        # New gates from 2026-05-26 TOP-10 manual audit (book-rule
        # parity). Order matters — strictest book-rule violations first
        # so the downgrade reason names the most fundamental issue.
        #
        # NOTE: is_monthly_240ma_missing was originally a downgrade
        # trigger (F8) but rolling it out against TOP 10 showed it
        # caught 8/10 candidates — the book's canonical 240MA is
        # WEEKLY (ch.4 "1년 매수 심리"), and the monthly variant is
        # the longer-horizon variant, not the load-bearing gate.
        # BookVerdict still surfaces a warning when monthly_240 is
        # missing; eligibility no longer downgrades on it alone.
        below_240 = is_below_weekly_240ma(result)
        stretched_240 = is_240ma_stretched(result)
        candle_top = is_candle_reversal_at_top(result)
        ambush = (not stale_pattern and not post_rally
                  and not below_240
                  and not stretched_240
                  and not candle_top
                  and is_ambush_setup(result))
        downgrade = (
            ambush or stale_pattern or post_rally
            or below_240 or stretched_240 or candle_top
        )
        if downgrade:
            if below_240:
                reason = "주봉 240MA 아래 — 책 기준 죽은 차트 영역"
                reason_code = "below_weekly_240"
            elif stretched_240:
                reason = "240MA 대비 +50% 위 — 책의 신규 진입 영역 벗어남"
                reason_code = "stretched_240"
            elif post_rally:
                reason = "랠리 후 조정 (반전 위험)"
                reason_code = "post_rally"
            elif candle_top:
                reason = "마지막 캔들 반전 신호 + 랠리 끝 (위꼬리 음봉 / 교수형 / 도지)"
                reason_code = "candle_top"
            elif stale_pattern:
                reason = "이미 매수 자리 한참 지남"
                reason_code = "stale"
            else:
                reason = "박스권 횡보 중 (포킹 발사 대기)"
                reason_code = "ambush"
            return {
                "grade": "CONDITIONAL",
                "icon": "⚠️",
                "headline": "오늘 매수 자격: 조건부 — 지금은 자리 X",
                "body": (
                    f"{reason}. 시스템이 STRONG_BUY 라벨 줬지만 실제 진입 "
                    "자리는 아닙니다 — 책 정신상 매수 X."
                ),
                "reason_code": reason_code,
            }

    # 2) Normal mapping per action.
    stretch_reason = result.get("stretch_reason")
    stretch_hold = action == "HOLD" and bool(stretch_reason)
    reaper = _is_reaper(result) and action in ("SELL", "SELL_OR_SHORT")

    if action == "STRONG_BUY":
        return {
            "grade": "OK",
            "icon": "✅",
            "headline": "오늘 매수 자격: 가능 (강한 매수)",
            "body": "책 정신상 매수해도 되는 자리. 본인 차트 검증 후 진입.",
            "reason_code": None,
        }
    if action == "BUY":
        return {
            "grade": "OK",
            "icon": "✅",
            "headline": "오늘 매수 자격: 가능 (매수)",
            "body": "책 정신상 매수 자리. 본인 차트 + 펀더 검증 통과 시에만 진입.",
            "reason_code": None,
        }
    if action == "HOLD":
        if stretch_hold:
            return {
                "grade": "CONDITIONAL",
                "icon": "⚠️",
                "headline": "오늘 매수 자격: 조건부 — 자리 지남",
                "body": "추세는 살아있지만 신규 매수 자리는 한참 지남. "
                        "보유 중이면 유지, 신규는 X.",
                "reason_code": "stretch_hold",
            }
        return {
            "grade": "WATCH",
            "icon": "⏸",
            "headline": "오늘 매수 자격: 관망",
            "body": "보유 중이면 유지 OK, 신규 매수는 자격 X. "
                    "다음 주봉 마감까지 대기.",
            "reason_code": None,
        }
    if action == "AVOID":
        return {
            "grade": "AVOID",
            "icon": "❌",
            "headline": "오늘 매수 자격: 없음 (회피)",
            "body": "장기 추세가 죽은 차트. 책 정신상 신규 매수 자격 X — "
                    "다른 종목 찾는 게 좋습니다.",
            "reason_code": None,
        }
    if action in ("SELL", "SELL_OR_SHORT"):
        if reaper:
            return {
                "grade": "EXIT",
                "icon": "🔴",
                "headline": "오늘 매수 자격: 없음 (저승사자 — 즉시 청산)",
                "body": "장대음봉이 주봉 10MA 동시 깬 상태. 보유 중이면 "
                        "즉시 청산, 신규 매수 자격 0%.",
                "reason_code": "reaper",
            }
        if action == "SELL":
            return {
                "grade": "EXIT",
                "icon": "🔴",
                "headline": "오늘 매수 자격: 없음 (매도 신호)",
                "body": "추세 종료 / 청산 신호. 보유 중이면 매도, 신규 매수 자격 X.",
                "reason_code": None,
            }
        return {
            "grade": "EXIT",
            "icon": "🔴",
            "headline": "오늘 매수 자격: 없음 (청산 또는 인버스)",
            "body": "추세 강하게 꺾임. 보유 중이면 매도 — 인버스 진입은 본인 판단.",
            "reason_code": None,
        }

    # Unknown action — surface a sensible default so the verdict card
    # never goes blank.
    return {
        "grade": "WATCH",
        "icon": "⏸",
        "headline": "오늘 매수 자격: 판단 보류",
        "body": "분석 결과를 해석할 수 없음. 페이지에서 직접 확인하세요.",
        "reason_code": None,
    }
