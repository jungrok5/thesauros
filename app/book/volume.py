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
    # 0.6 was too strict — a borderline drop (e.g., 0.62 for 국보디자인
    # 2026-05-22) fell through every case and landed in case 0 "분류 불명확",
    # despite being the textbook "물량 소진 + 매복" pattern. Relax to 0.7
    # so the obvious convergence-with-drying-volume zone is caught.
    VOL_DOWN = vol_ratio <= 0.7
    VOL_DRY = vol_ratio <= 0.5     # severe drop ("씨가 마름")
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
    # Book p364 reading: 거래량 ≥ 3× 평균이면 "세력 털기" 거의 확정.
    # Additional confirmation = a strong upper-wick rejection candle on
    # any of the last 4 bars (long upper wick + small body = price
    # refused at the high). LG우 2026-05-15 pattern: high 98,700 vs
    # close 79,000 with vol = 7× median = textbook case 9 강버전.
    if zone == "top" and VOL_SURGE:
        # Confidence boosted when any recent bar shows the rejection
        # signature the book describes.
        rejection = False
        try:
            recent = df.tail(4)
            for _, row in recent.iterrows():
                o, h, l, c = (float(row["open"]), float(row["high"]),
                              float(row["low"]), float(row["close"]))
                rng = max(h - l, 1e-9)
                body = abs(c - o)
                upper = h - max(o, c)
                if (
                    upper / rng >= 0.4
                    and body / rng < 0.5
                    and upper >= 2 * body
                ):
                    rejection = True
                    break
        except Exception:
            pass
        return VolumeCase(
            case=9,
            label_kr=(
                "상투권 거래량 폭증 + 위꼬리 거부 (세력 털기 확정)"
                if rejection
                else "상투권 거래량 폭증 (세력 털기 위험)"
            ),
            direction="bearish",
            confidence=0.85 if rejection else 0.75,
            reason=(
                f"고점권 거래량 +{(vol_ratio-1)*100:.0f}% (책 3배 기준 초과)"
                + (" + 위꼬리 거부 캔들" if rejection else "")
                + ". 책 케이스 9."
            ),
        )
    # Weaker variant: top + moderate volume rise (1.5×~3.0×) without
    # rejection candle. Book is less definitive here — could be 손바뀜
    # with continuation OR early distribution. Surface as a soft warning.
    if zone == "top" and VOL_UP:
        return VolumeCase(
            case=9,
            label_kr="상투권 거래량 증가 (관찰)",
            direction="neutral",
            confidence=0.5,
            reason=(
                f"고점권 거래량 +{(vol_ratio-1)*100:.0f}% (책 3배 기준 미달)."
                " 손바뀜 후 추가 상승 가능성도. 책 케이스 9 약버전."
            ),
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
    # ---- Case 12: 수렴기 거래량 감소 (책: 매물 소진 + 폭발 전조).
    # Priority over case 2 — when the zone is middle/bottom and the
    # recent move was up or flat with volume drying up, this is the
    # "기간 조정 / 빨래 널기" setup (개미 털기 + accumulation finishing),
    # not the dead-chart case 2 (which is sideways for a long time with
    # no upthrust hidden in the past). Differentiator: zone.
    if zone in ("middle", "bottom") and trend in (UP, SIDE) and VOL_DOWN:
        confidence = 0.70 if VOL_DRY else 0.62
        return VolumeCase(
            case=12,
            label_kr="수렴기 거래량 감소 (매물 소진, 폭발 전조)",
            direction="bullish",
            confidence=confidence,
            reason=(
                f"거래량 -{(1-vol_ratio)*100:.0f}%, 가격대 {zone}/{trend} — "
                "책: 기간 조정으로 개미 털고 매물 소진. 포킹 발사 대기."
            ),
        )

    # ---- Case 2: top-zone sideways + volume down → true dead chart.
    # The "buyer interest evaporated AT THE TOP" pattern. Middle/bottom
    # zone with vol_down is case 12 above (accumulation), not death.
    if VOL_DOWN and trend == SIDE and zone == "top":
        return VolumeCase(
            case=2,
            label_kr="거래량 감소 횡보 (죽은 차트)",
            direction="bearish",
            confidence=0.55,
            reason="매수세 증발, 추세 사망. 책 케이스 2.",
        )

    # ---- Case 1: sideways + flat volume (책 케이스 1 본래 정의)
    if trend == SIDE and not (VOL_UP or VOL_DOWN):
        return VolumeCase(
            case=1,
            label_kr="가격대 + 거래량 횡보",
            direction="neutral",
            confidence=0.45,
            reason="큰 상승 신호 없음, 분산 상태. 책 케이스 1.",
        )

    # ---- Soft fallback: meaningful zone/trend combos that don't fit
    # any of the 11 book cases sharply (e.g. middle-zone + uptrend +
    # mild-volume-up like IONQ 2026-05-18 with vol_ratio=1.27). The
    # book labels these as "Case 1 변형" — interpretable context, not
    # high-conviction signal. We surface them as low-confidence
    # neutrals instead of letting them fall into "분류 불명확".
    if trend == UP:
        if zone == "top":
            # Top-zone uptrend with moderate volume — could be either
            # late-stage 매집 (vol ≤ 1.0, mild distribution risk) or
            # continuation (vol slightly up, neither surge nor drying).
            # Book treats this as "추세 막바지 관찰" — confidence low.
            if vol_ratio < 1.0:
                return VolumeCase(
                    case=7,
                    label_kr="상투권 거래량 약감소 (매집 후반)",
                    direction="neutral",
                    confidence=0.45,
                    reason=(
                        f"상투권 상승 + 거래량 -{(1-vol_ratio)*100:.0f}%. "
                        "책 case 7 변형: 세력 매집 마무리 가능성, "
                        "하지만 case 9 (털기) 직전일 수도. 위꼬리 봉 주시."
                    ),
                )
            return VolumeCase(
                case=1,
                label_kr="상투권 추세 진행 (변동성 평이)",
                direction="neutral",
                confidence=0.40,
                reason=(
                    f"상투권 +{(vol_ratio-1)*100:.0f}% 거래량 (3배 미달). "
                    "추세 유지되지만 신규 매수 자리 X — 책: 보유 평가용."
                ),
            )
        if zone == "middle":
            return VolumeCase(
                case=1,
                label_kr="추세 진행 중 (정상 거래량)",
                direction="neutral",
                confidence=0.40,
                reason=(
                    f"중간대 상승 추세, 거래량 +{(vol_ratio-1)*100:.0f}% "
                    "(폭증 미달). 책: 큰 신호 없음, 추세 유지 관찰."
                ),
            )
        if zone == "bottom":
            return VolumeCase(
                case=1,
                label_kr="바닥 반전 시도 (확정 미흡)",
                direction="neutral",
                confidence=0.40,
                reason=(
                    f"바닥권 상승 시도, 거래량 +{(vol_ratio-1)*100:.0f}% "
                    "(3배 임계 미달). 책: case 3 후보, 거래량 확인 필요."
                ),
            )
    if trend == DOWN:
        if zone == "top":
            return VolumeCase(
                case=10,
                label_kr="상투 후 급락 시작 (위험)",
                direction="bearish",
                confidence=0.55,
                reason=(
                    f"상투권 + 하락 추세, 거래량 {vol_ratio:.2f}×. "
                    "책 case 10: 세력 설거지 의심. 청산 + 신규 매수 X."
                ),
            )
        if zone == "middle":
            return VolumeCase(
                case=11,
                label_kr="조정 진행 (위험 관찰)",
                direction="bearish",
                confidence=0.40,
                reason=(
                    "중간대 조정 진행. 거래량 결정적 시그널 부재. "
                    "10MA 이탈 시 청산 권고."
                ),
            )
    if trend == SIDE:
        return VolumeCase(
            case=1,
            label_kr=f"{zone}대 박스권 (방향성 미정)",
            direction="neutral",
            confidence=0.35,
            reason=(
                f"가격대 {zone} 박스권, 거래량 {vol_ratio:.2f}× "
                "(특이 신호 없음). 책: 매매 보류."
            ),
        )

    return VolumeCase(
        case=0,
        label_kr="분류 불명확",
        direction="neutral",
        confidence=0.30,
        reason=f"zone={zone}, trend={trend}, vol_ratio={vol_ratio:.2f}",
    )


# ---------------------------------------------------------------------------
# 역매집 캔들 — 긴 위꼬리 역망치형 반복
# ---------------------------------------------------------------------------
def detect_volume_node(df: pd.DataFrame,
                        bins: int = 20,
                        lookback: int = 200,
                        node_percentile: float = 80) -> Optional[Dict]:
    """마덧값 (Volume-by-Price / 매물대 클러스터) — 책 5장.

    가격 구간별 누적 거래량 분포 → 상위 매물대 노드 식별.
    현재가가 그 노드를 위로 돌파하면 강력한 지지, 아래로 깨면 저항.

    returns: {
      'nodes': [{'price_low', 'price_high', 'volume_total', 'rank'}],
      'current_price_zone': 'support' / 'resistance' / 'neutral',
      'nearest_node_dist_pct': float,
    }
    """
    if df is None or len(df) < lookback or "volume" not in df.columns:
        return None
    tail = df.tail(lookback)
    lo = float(tail["low"].min())
    hi = float(tail["high"].max())
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    if step <= 0:
        return None

    volumes = np.zeros(bins)
    for _, row in tail.iterrows():
        rng_lo = (float(row["low"]) - lo) / step
        rng_hi = (float(row["high"]) - lo) / step
        i0 = max(0, int(np.floor(rng_lo)))
        i1 = min(bins - 1, int(np.ceil(rng_hi)))
        if i1 > i0:
            volumes[i0:i1+1] += float(row["volume"]) / (i1 - i0 + 1)
        else:
            volumes[i0] += float(row["volume"])

    threshold = np.percentile(volumes, node_percentile)
    nodes = []
    for i in range(bins):
        if volumes[i] >= threshold and volumes[i] > 0:
            nodes.append({
                "price_low": lo + i * step,
                "price_high": lo + (i + 1) * step,
                "volume_total": float(volumes[i]),
                "rank": i,
            })
    if not nodes:
        return None

    nodes.sort(key=lambda n: -n["volume_total"])
    nodes = nodes[:5]  # top 5 nodes

    cur = float(df["close"].iloc[-1])
    nearest = min(nodes, key=lambda n: min(abs(cur - n["price_low"]),
                                            abs(cur - n["price_high"])))
    node_mid = (nearest["price_low"] + nearest["price_high"]) / 2
    dist_pct = (cur - node_mid) / cur if cur > 0 else 0

    if dist_pct > 0.005:
        zone = "support"  # 가격이 노드 위 → 매물대가 아래에서 지지
    elif dist_pct < -0.005:
        zone = "resistance"  # 가격이 노드 아래 → 매물대가 위에서 저항
    else:
        zone = "neutral"

    return {
        "nodes": nodes,
        "current_price_zone": zone,
        "nearest_node_dist_pct": dist_pct,
        "nearest_node_price_mid": node_mid,
    }


def detect_531_accumulation(df: pd.DataFrame,
                             min_total_bars: int = 80) -> Optional[Dict]:
    """5,3,3-1 매집 파동 (책 p366-367).

    매집(5봉 상승) → Test(3봉 조정) → 최종 Test(3봉 조정, 깊이 더 작음)
    → 1봉 본격 상승 시작.

    단순화 알고리즘:
      - 최근 12봉 정도를 [5, 3, 3, 1] 구간으로 나눠 검사
      - 5봉: 상승 + 거래량 ↑
      - 첫 3봉: 조정 (소폭 하락 또는 횡보), 거래량 ↓
      - 다음 3봉: 조정 (첫 조정보다 더 얕음), 거래량 더 ↓
      - 마지막 1봉: 장대양봉 + 거래량 ↑↑
    """
    if df is None or len(df) < min_total_bars:
        return None
    tail = df.tail(12).reset_index(drop=True)
    if len(tail) < 12 or "volume" not in tail.columns:
        return None

    seg_accum = tail.iloc[0:5]
    seg_test1 = tail.iloc[5:8]
    seg_test2 = tail.iloc[8:11]
    seg_burst = tail.iloc[11:12]

    # 1. 5봉 매집: 상승
    accum_ret = (seg_accum["close"].iloc[-1] - seg_accum["close"].iloc[0]) / seg_accum["close"].iloc[0]
    if accum_ret < 0.03:
        return None
    accum_vol = float(seg_accum["volume"].mean())

    # 2. 첫 3봉 Test: 조정 (-5% ~ +1%)
    test1_high = seg_accum["close"].iloc[-1]
    test1_low = float(seg_test1["low"].min())
    test1_depth = (test1_high - test1_low) / test1_high
    if test1_depth < 0.01 or test1_depth > 0.10:
        return None
    test1_vol = float(seg_test1["volume"].mean())
    if test1_vol >= accum_vol:
        return None  # 조정인데 거래량 그대로 = 매집 아님

    # 3. 두번째 3봉 Test: 더 얕은 조정
    test2_high = float(seg_test1["close"].iloc[-1])
    test2_low = float(seg_test2["low"].min())
    test2_depth = (test2_high - test2_low) / test2_high if test2_high > 0 else 0
    if test2_depth >= test1_depth:
        return None  # 더 얕아야 함
    test2_vol = float(seg_test2["volume"].mean())
    if test2_vol >= test1_vol * 1.1:
        return None  # 더 줄어야 함

    # 4. 마지막 봉: 장대양봉 + 큰 거래량
    burst = seg_burst.iloc[0]
    burst_body = float(burst["close"]) - float(burst["open"])
    if burst_body <= 0:
        return None
    body_avg = (tail["close"] - tail["open"]).abs().iloc[:-1].mean()
    if body_avg <= 0 or burst_body < body_avg * 1.8:
        return None
    burst_vol = float(burst["volume"])
    if burst_vol < test2_vol * 1.8:
        return None

    return {
        "detected": True,
        "accum_return_pct": accum_ret * 100,
        "test1_depth_pct": test1_depth * 100,
        "test2_depth_pct": test2_depth * 100,
        "burst_body_x_avg": float(burst_body / body_avg),
        "burst_vol_x_test2": float(burst_vol / test2_vol),
        "confidence": min(0.92,
                          0.72 + (test1_depth - test2_depth) * 2 + min(0.10, (burst_vol / max(accum_vol, 1) - 1) * 0.05)),
        "reason": (
            f"5,3,3-1 매집: 상승 {accum_ret*100:.1f}% → "
            f"Test1 -{test1_depth*100:.1f}% (거래량↓) → "
            f"Test2 -{test2_depth*100:.1f}% (더 얕음, 거래량↓↓) → "
            f"장대양봉 ({burst_body/body_avg:.1f}x body, "
            f"{burst_vol/test2_vol:.1f}x volume). 책: 본격 상승 시작."
        ),
    }


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
