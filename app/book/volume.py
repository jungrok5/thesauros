"""Volume analysis — 책 5장 (가격대별 거래량 11유형 + 역매집 캔들).

11가지 케이스 표 (p364):
   1. 가격대 거래량 횡보 → 큰 상승 없음 (분산)
   2. 가격대 거래량 감소 → 매수세 증발, 죽은 차트
   3. 바닥권 거래량 증가 (>3x avg) → 추세 반전 매수 신호 ⭐
   4. 바닥권 급락 중 거래량 감소 → 받쳐주는 물량 多, 하락 지속
   5. 바닥권 급락 중 거래량 증가 →
        ① 우량주: 매수 기회
        ② 부실주: 대주주 매물 출회
   6. 급등 초기 거래량 증가 → 개미에게 던지는 자리 가능 (조심)
   7. 급등 중 거래량 감소 → 세력 매집 완료 (좋음)
   8. 상투권 거래량 감소 → 세력이 개인에게 맡김
   9. 상투권 거래량 증가 → 세력 털기 / 손바뀜 (위험)
  10. 상투 후 급락 초기 거래량 증가 → 기대치 잔존 / 세력 설거지
  11. 상투 후 급락 중 거래량 감소 → 죽은 차트 (개미만 남음)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class VolumeCase:
    case: int                # 1..11
    label_kr: str
    direction: str           # "bullish" / "bearish" / "neutral"
    confidence: float        # 0-1
    reason: str

    def to_dict(self) -> Dict:
        return {
            "case": self.case,
            "label_kr": self.label_kr,
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
        }


def _price_zone(df: pd.DataFrame, window: int = 252) -> str:
    """Classify current price into bottom / middle / top of recent range."""
    tail = df.tail(window)
    lo = float(tail["low"].min())
    hi = float(tail["high"].max())
    cur = float(df["close"].iloc[-1])
    if hi <= lo:
        return "middle"
    pos = (cur - lo) / (hi - lo)
    if pos < 0.30:
        return "bottom"
    if pos > 0.70:
        return "top"
    return "middle"


def _short_trend(df: pd.DataFrame, days: int = 20) -> str:
    """Up / down / sideways over the last `days`."""
    tail = df.tail(days + 1)
    if len(tail) < 3:
        return "sideways"
    chg = (float(tail["close"].iloc[-1]) - float(tail["close"].iloc[0])) / float(tail["close"].iloc[0])
    if chg > 0.05:
        return "up"
    if chg < -0.05:
        return "down"
    return "sideways"


def _volume_change(df: pd.DataFrame, days: int = 20) -> float:
    """Recent (last days/2) vs prior (days/2..days) average volume ratio."""
    if "volume" not in df.columns or len(df) < days:
        return 1.0
    tail = df.tail(days)
    half = days // 2
    recent = tail["volume"].tail(half).mean()
    prior = tail["volume"].head(half).mean()
    if prior <= 0:
        return 1.0
    return float(recent / prior)


def classify_volume_case(df: pd.DataFrame, window: int = 252,
                         days: int = 20) -> Optional[VolumeCase]:
    """Return the dominant 11-case volume classification for the current bar."""
    if df is None or len(df) < days + 5:
        return None

    zone = _price_zone(df, window)
    trend = _short_trend(df, days)
    vol_ratio = _volume_change(df, days)

    UP, DOWN, SIDE = "up", "down", "sideways"
    VOL_UP = vol_ratio >= 1.5
    VOL_DOWN = vol_ratio <= 0.6
    VOL_SURGE = vol_ratio >= 3.0

    # ---- Case 3: bottom + volume surge → reversal buy ⭐
    if zone == "bottom" and VOL_SURGE:
        return VolumeCase(
            case=3,
            label_kr="바닥권 거래량 폭증 (추세 반전 매수)",
            direction="bullish",
            confidence=0.85,
            reason=f"거래량 +{(vol_ratio-1)*100:.0f}%, 바닥권 자리. 책 케이스 3.",
        )
    # ---- Case 7: rising + volume drop → smart money fully accumulated
    if zone == "middle" and trend == UP and VOL_DOWN:
        return VolumeCase(
            case=7,
            label_kr="급등 중 거래량 감소 (세력 매집 완료)",
            direction="bullish",
            confidence=0.78,
            reason=f"상승 추세인데 거래량 -{(1-vol_ratio)*100:.0f}%. 책 케이스 7.",
        )
    # ---- Case 9: top + volume surge → distribution risk
    if zone == "top" and VOL_UP:
        return VolumeCase(
            case=9,
            label_kr="상투권 거래량 증가 (세력 털기 위험)",
            direction="bearish",
            confidence=0.72,
            reason=f"고점권에서 거래량 +{(vol_ratio-1)*100:.0f}%. 책 케이스 9.",
        )
    # ---- Case 5: bottom + falling + volume up
    if zone == "bottom" and trend == DOWN and VOL_UP:
        return VolumeCase(
            case=5,
            label_kr="바닥권 급락 중 거래량 증가",
            direction="neutral",
            confidence=0.55,
            reason="우량주면 매수 기회, 부실주면 대주주 매물. 종목 질로 판단. 책 케이스 5.",
        )
    # ---- Case 4: bottom + falling + volume down
    if zone == "bottom" and trend == DOWN and VOL_DOWN:
        return VolumeCase(
            case=4,
            label_kr="바닥권 급락 중 거래량 감소",
            direction="bearish",
            confidence=0.65,
            reason="받쳐주는 물량이 많은 상태로 하락 지속 가능. 책 케이스 4.",
        )
    # ---- Case 11: top → falling + volume drop
    if zone in ("top", "middle") and trend == DOWN and VOL_DOWN:
        return VolumeCase(
            case=11,
            label_kr="상투 후 급락 + 거래량 감소 (죽은 차트)",
            direction="bearish",
            confidence=0.70,
            reason="세력 떠나고 개미만 남은 상태. 회피. 책 케이스 11.",
        )
    # ---- Case 6: rising start + volume surge (early)
    if zone == "middle" and trend == UP and VOL_SURGE:
        return VolumeCase(
            case=6,
            label_kr="상승 초기 거래량 폭증",
            direction="neutral",
            confidence=0.55,
            reason="개미에게 떠넘기는 자리일 수 있음, 신중히. 책 케이스 6.",
        )
    # ---- Case 8: top + volume drop
    if zone == "top" and VOL_DOWN:
        return VolumeCase(
            case=8,
            label_kr="상투권 거래량 감소 (세력 위임)",
            direction="neutral",
            confidence=0.50,
            reason="세력이 개인에게 시장 맡김. 다음 움직임 관찰. 책 케이스 8.",
        )
    # ---- Case 1: sideways + flat volume
    if trend == SIDE and not (VOL_UP or VOL_DOWN):
        return VolumeCase(
            case=1,
            label_kr="가격대 + 거래량 횡보",
            direction="neutral",
            confidence=0.45,
            reason="큰 상승 신호 없음, 분산 상태. 책 케이스 1.",
        )
    # ---- Case 2: sideways + volume down
    if VOL_DOWN and trend == SIDE:
        return VolumeCase(
            case=2,
            label_kr="거래량 감소 횡보 (죽은 차트)",
            direction="bearish",
            confidence=0.55,
            reason="매수세 증발, 추세 사망. 책 케이스 2.",
        )

    return VolumeCase(
        case=0,
        label_kr="분류 불명확",
        direction="neutral",
        confidence=0.40,
        reason=f"zone={zone}, trend={trend}, vol_ratio={vol_ratio:.2f}",
    )


# ---------------------------------------------------------------------------
# 역매집 캔들 — 긴 위꼬리 역망치형 반복
# ---------------------------------------------------------------------------
def detect_reverse_accumulation(df: pd.DataFrame,
                                window: int = 30,
                                min_occurrences: int = 3) -> Optional[Dict]:
    """역매집 캔들 (긴 위꼬리 역망치) 반복 + 바닥 보존 감지.

    Book p368-369: 세력 존재 증거. 진입 = 후속 후킹 캔들.
    """
    if df is None or len(df) < window + 5:
        return None
    tail = df.tail(window).reset_index(drop=True)

    def is_inverted_hammer(row) -> bool:
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        rng = h - l
        if rng <= 0:
            return False
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        return (
            body > 0
            and upper > body * 1.5
            and lower < body * 0.5
            and body / rng < 0.4
        )

    matches = []
    for i, row in tail.iterrows():
        if is_inverted_hammer(row):
            matches.append(i)

    if len(matches) < min_occurrences:
        return None

    # Check that the floor (lowest low) isn't materially broken
    floor = float(tail.iloc[matches[0]]["low"])
    later_lows = tail.iloc[matches[0]+1:]["low"].min() if matches[0]+1 < len(tail) else floor
    if pd.notna(later_lows) and later_lows < floor * 0.95:
        return None

    return {
        "detected": True,
        "occurrences": len(matches),
        "first_idx": matches[0],
        "last_idx": matches[-1],
        "floor": round(floor, 4),
        "reason": (
            f"역망치 캔들 {len(matches)}회 반복 + 바닥({floor:.2f}) 보존. "
            "책: 세력 매집 존재의 강력한 증거 ('심봤다')."
        ),
    }
