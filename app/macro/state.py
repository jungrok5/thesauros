"""Interpret each macro indicator into a state with a human-readable verdict.

State levels (UI-friendly):
  BULL       — 자산 시장에 우호적
  NEUTRAL    — 보통
  CAUTION    — 주의 (책 관점에서 risk-off 신호 일부)
  BEAR       — 자산 시장에 부정적

Each indicator gets:
  value:   latest reading
  yoy:     YoY % change (if applicable)
  state:   BULL / NEUTRAL / CAUTION / BEAR
  verdict: short Korean sentence explaining current state per book guidance
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.macro.fetch import history, latest_value
from app.macro.indicators import INDICATORS, CATEGORY_ORDER, CATEGORY_LABEL_KR


STATE_RANK = {"BULL": 1, "NEUTRAL": 0, "CAUTION": -1, "BEAR": -2}


@dataclass
class IndicatorState:
    key: str
    name_kr: str
    category: str
    book_ref: str
    desc: str
    value: Optional[float]
    as_of: Optional[date]
    yoy_pct: Optional[float]
    state: str
    verdict: str
    unit: str

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "name_kr": self.name_kr,
            "category": self.category,
            "book_ref": self.book_ref,
            "desc": self.desc,
            "value": (round(self.value, 4) if self.value is not None else None),
            "as_of": (str(self.as_of) if self.as_of else None),
            "yoy_pct": (round(self.yoy_pct, 2) if self.yoy_pct is not None else None),
            "state": self.state,
            "verdict": self.verdict,
            "unit": self.unit,
        }


def _yoy_pct(df: pd.DataFrame) -> Optional[float]:
    """YoY % change of last value vs ~252 trading days / ~365 calendar days ago."""
    if df.empty or len(df) < 5:
        return None
    df = df.sort_values("date")
    last = df.iloc[-1]
    cutoff = pd.to_datetime(last["date"]) - pd.Timedelta(days=365)
    prior = df[pd.to_datetime(df["date"]) <= cutoff]
    if prior.empty:
        return None
    base = float(prior.iloc[-1]["value"])
    if base == 0:
        return None
    return (float(last["value"]) - base) / abs(base) * 100.0


def _classify(value: float, yoy: Optional[float], thresholds: Dict, hist: pd.DataFrame
              ) -> tuple[str, str]:
    """Return (state, verdict_kr) per threshold-rule type.

    Verdict text is **meaning only** — the dashboard card renders
    `value + unit` separately in its own cell, so the verdict line
    used to display "211000.00% — 침체 진행" for unemployment-claims
    (raw count, K units) just because the unemployment-rate branch
    hardcoded "%" into the f-string. Now: drop the redundant value/
    unit from verdict text, keep only the qualitative judgement.
    """
    t = thresholds.get("type", "")

    if t == "yoy_pct":
        # 통화량/원자재류
        if yoy is None:
            return "NEUTRAL", "기준 YoY 데이터 부족"
        if yoy >= thresholds["bull"]:
            return "BULL", "자산 가격에 매우 우호"
        if yoy >= thresholds["neutral"]:
            return "BULL", "우호적 흐름"
        if yoy >= thresholds["weak"]:
            return "NEUTRAL", "평이"
        if yoy >= thresholds["bear"]:
            return "CAUTION", "약함"
        return "BEAR", "부정적, 위축"

    if t == "yoy_pct_optimal":
        # 인플레이션 (적정 밴드 벗어나면 둘 다 안 좋음)
        if yoy is None:
            return "NEUTRAL", "YoY 미산정"
        if thresholds["danger_low"] <= yoy <= thresholds["danger_high"]:
            if thresholds["optimal_low"] <= yoy <= thresholds["optimal_high"]:
                return "BULL", "Fed 타겟 부근, 이상적"
            if thresholds["warn_low"] <= yoy <= thresholds["warn_high"]:
                return "NEUTRAL", "적정 밴드"
            if yoy > thresholds["warn_high"]:
                return "CAUTION", "인플레 과열 진행 중"
            return "CAUTION", "디스인플레/디플레 우려"
        if yoy > thresholds["danger_high"]:
            return "BEAR", "인플레이션 위험"
        return "BEAR", "디플레이션 위험"

    if t == "sign":
        # 수익률곡선
        if value < thresholds["inverted_warn"]:
            return "BEAR", "역전됨 → 18~24개월 내 침체 가능 (책 핵심 경고)"
        if value < thresholds["flattening_warn"]:
            return "CAUTION", "평탄화, 침체 위험 누적"
        return "BULL", "정상 형태, 경기 확장 시그널"

    if t == "level":
        good_max = thresholds.get("good_max")
        warn_max = thresholds.get("warn_max")
        bad_max = thresholds.get("bad_max")
        good_min = thresholds.get("good_min")
        neutral_min = thresholds.get("neutral_min")
        calm_max = thresholds.get("calm_max")
        warn_min = thresholds.get("warn_min")
        panic_min = thresholds.get("panic_min")

        # VIX / 스프레드 (낮을수록 좋음)
        if calm_max is not None:
            if value <= calm_max:
                return "BULL", "평온, 리스크온 환경"
            if value < warn_min:
                return "NEUTRAL", "평상시 범위"
            if value < panic_min:
                return "CAUTION", "변동성 확대, 주의"
            return "BEAR", "공포 / 신용 경색"

        # 실업률 (낮을수록 좋음) — and also incidentally what
        # 실업수당청구 / 주택 착공 etc fall into. Verdict text says
        # the meaning without claiming a "%" unit (caller's unit
        # metadata is the source of truth).
        if good_max is not None and bad_max is not None:
            if value <= good_max:
                return "BULL", "고용 강함"
            if value <= warn_max:
                return "NEUTRAL", "보통"
            if value <= bad_max:
                return "CAUTION", "약화 신호"
            return "BEAR", "침체 진행"

        # PMI (높을수록 좋음, 50 기준)
        if good_min is not None and neutral_min is not None:
            if value >= good_min:
                return "BULL", "경기 확장 (50 위)"
            if value >= neutral_min:
                return "NEUTRAL", "경기 정체"
            return "BEAR", "경기 수축"

        return "NEUTRAL", ""

    if t == "level_yoy":
        bull_level_max = thresholds.get("bull_level_max", 999)
        yoy_up = thresholds.get("yoy_up", 0.5)
        yoy_down = thresholds.get("yoy_down", -0.5)
        if yoy is not None:
            if value < bull_level_max and yoy <= yoy_down:
                return "BULL", "인하 사이클, 자산 우호"
            if yoy >= yoy_up and value > bull_level_max:
                return "BEAR", "인상 사이클, 자산 압박"
        if value < bull_level_max:
            return "NEUTRAL", "완화적 수준"
        return "CAUTION", "긴축적 수준"

    if t == "band":
        low, ml, mh, hi = thresholds["low"], thresholds["mid_low"], thresholds["mid_high"], thresholds["high"]
        if value < low:
            return "CAUTION", "매우 낮음"
        if value < ml:
            return "NEUTRAL", "낮은 편"
        if value <= mh:
            return "BULL" if (ml <= value <= mh) else "NEUTRAL", "적정 범위"
        if value <= hi:
            return "CAUTION", "다소 높음"
        return "BEAR", "매우 높음"

    if t == "trend_ma200":
        if hist.empty or len(hist) < 50:
            return "NEUTRAL", "200MA 산정 불가"
        ma200 = hist["value"].tail(200).mean()
        ratio = (value - ma200) / ma200 * 100
        if ratio > 5:
            return "BULL", f"200MA 대비 +{ratio:.1f}% · 상승 추세 (책 탑다운 우호)"
        if ratio > -3:
            return "NEUTRAL", f"200MA {ratio:+.1f}% · 추세 전환 구간"
        return "BEAR", f"200MA 대비 {ratio:.1f}% · 하락 추세 (책: 인버스/현금)"

    return "NEUTRAL", f"{value}"


def state_for(key: str) -> Optional[IndicatorState]:
    """Compute current state for one indicator. Returns None if data missing."""
    ind = next((i for i in INDICATORS if i["key"] == key), None)
    if ind is None:
        return None

    latest = latest_value(ind["series_id"])
    if latest is None:
        return None
    value = float(latest["value"])
    as_of = latest["date"]

    hist = history(ind["series_id"], years=3)
    yoy = _yoy_pct(hist)

    state, verdict = _classify(value, yoy, ind["thresholds"], hist)
    return IndicatorState(
        key=key,
        name_kr=ind["name_kr"],
        category=ind["category"],
        book_ref=ind["book_ref"],
        desc=ind["desc"],
        value=value,
        as_of=as_of,
        yoy_pct=yoy,
        state=state,
        verdict=verdict,
        unit=ind["unit"],
    )


def all_states() -> List[IndicatorState]:
    out = []
    for ind in INDICATORS:
        s = state_for(ind["key"])
        if s is not None:
            out.append(s)
    return out


def market_regime() -> Dict:
    """Aggregate all indicator states into an overall market regime label.

    Book's framework (시장 심리 사이클):
      공포 (FEAR)              — VIX 높음, 신용스프레드 확대, 지수 200MA 하향
      기대반의심반 (HOPE_DOUBT) — 회복 시작, 거시 혼조
      희망 (HOPE)              — 거시 우호 + 지수 상승 추세
      확신 (CONVICTION)        — 모든 지표 BULL + VIX 낮음 (버블 경계!)
    """
    states = all_states()
    if not states:
        return {"regime": "UNKNOWN", "score": 0, "n_indicators": 0, "components": []}

    score_sum = sum(STATE_RANK.get(s.state, 0) for s in states)
    n = len(states)
    avg = score_sum / n

    # VIX 분리 체크
    vix = next((s for s in states if s.key == "vix"), None)
    breadth_states = [s for s in states if s.category == "breadth"]
    breadth_bull = sum(1 for s in breadth_states if s.state == "BULL")
    breadth_bear = sum(1 for s in breadth_states if s.state in ("CAUTION", "BEAR"))

    # Yield curve
    yc = next((s for s in states if s.key == "yield_curve_10y_2y"), None)
    yc_inverted = yc and yc.state == "BEAR"

    if avg > 0.5 and vix and vix.state == "BULL" and breadth_bull >= 2:
        regime = "CONVICTION"
        note = "버블 단계 경계 — 책: 노출 축소 권고"
    elif avg > 0.2 and breadth_bull >= 1:
        regime = "HOPE"
        note = "본격 상승 단계"
    elif -0.3 <= avg <= 0.2:
        regime = "HOPE_DOUBT"
        note = "기대 반 의심 반, 신중 진입"
    elif vix and vix.state in ("CAUTION", "BEAR"):
        regime = "FEAR"
        note = "공포 단계 — 인버스/현금 고려, 또는 매수 기회 (책: 위기=기회)"
    else:
        regime = "RISK_OFF"
        note = "리스크 회피, 매매 보류 권장"

    components = [
        {"key": s.key, "name_kr": s.name_kr, "state": s.state, "verdict": s.verdict}
        for s in states
    ]

    return {
        "regime": regime,
        "score": round(avg, 2),
        "n_indicators": n,
        "vix_state": (vix.state if vix else None),
        "yield_curve_inverted": bool(yc_inverted),
        "note": note,
        "components": components,
    }


def categorized() -> Dict[str, List[Dict]]:
    """Return states grouped by category in book's preferred order."""
    out: Dict[str, List[Dict]] = {c: [] for c in CATEGORY_ORDER}
    for s in all_states():
        out.setdefault(s.category, []).append(s.to_dict())
    return {
        CATEGORY_LABEL_KR[c]: out[c]
        for c in CATEGORY_ORDER if out.get(c)
    }
