"""책의 모든 매매 시그널을 4가지 카테고리로 통합.

카테고리:
  ENTER  — 진입 (또는 첫 추매 unit)
  PYRAMID — 강한 상승 신호 / "팔자 고치는 패턴" 추매
  WARN   — 하락 경고 (다음 봉에서 확정되면 분할 매도)
  EXIT   — 무조건 청산 (저승사자 캔들 / 10MA 깸 / 손절선)

이 모듈은 한 시점 (한 bar) 의 가격 시계열을 받아 어떤 시그널이 발동하는지
하나의 SignalSet 으로 반환한다. 백테스트 엔진은 이걸 보고 state machine
을 돌린다.

책 출처는 각 시그널마다 주석으로 명시.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.book.candles import CandleParts, quarter_safety, classify_candle
from app.book.patterns import (
    detect_240ma_breakout,
    detect_cup_and_handle,
    detect_dolbanji,
    detect_double_bottom,
    detect_double_top,
    detect_forking,
    detect_head_and_shoulders,
    detect_reverse_head_and_shoulders,
    detect_triple_bottom,
    detect_triple_top,
)
from app.book.reversals import (
    detect_reversal_double_top_to_bottom,
    detect_reversal_double_bottom_to_top,
    detect_reversal_double_top_to_inv_hns,
    detect_reversal_single_candle,
)
from app.book.trend import add_moving_averages, MA_PERIODS
from app.book.volume import classify_volume_case, detect_reverse_accumulation


SignalKind = str   # "ENTER" / "PYRAMID" / "WARN" / "EXIT"


@dataclass
class Signal:
    kind: SignalKind
    source: str               # 책 출처 (e.g. "쌍바닥 (monthly)")
    confidence: float         # 0..1
    detail: str = ""          # 한국어 설명


@dataclass
class SignalSet:
    """한 bar 시점의 모든 시그널 모음."""
    date: pd.Timestamp
    close: float
    ma_10: Optional[float] = None
    ma_240: Optional[float] = None
    signals: List[Signal] = field(default_factory=list)

    def has(self, kind: SignalKind, min_conf: float = 0) -> bool:
        return any(s.kind == kind and s.confidence >= min_conf
                   for s in self.signals)

    def best(self, kind: SignalKind) -> Optional[Signal]:
        cand = [s for s in self.signals if s.kind == kind]
        if not cand:
            return None
        return max(cand, key=lambda s: s.confidence)

    def to_dict(self) -> Dict:
        return {
            "date": str(self.date.date() if hasattr(self.date, "date")
                        else self.date),
            "close": round(float(self.close), 4),
            "ma_10": round(float(self.ma_10), 4) if self.ma_10 else None,
            "ma_240": round(float(self.ma_240), 4) if self.ma_240 else None,
            "signals": [
                {"kind": s.kind, "source": s.source,
                 "confidence": round(s.confidence, 3), "detail": s.detail}
                for s in self.signals
            ],
        }


def _bar_view(df: pd.DataFrame, i: int, lookback: int = 200) -> pd.DataFrame:
    """Bar i 까지의 윈도우 (룩어헤드 차단)."""
    start = max(0, i - lookback + 1)
    return df.iloc[start: i + 1].copy().reset_index(drop=True)


def _is_double_top_forming(window: pd.DataFrame, tol: float = 0.05) -> bool:
    """쌍봉이 모양만 보이지만 10MA 아직 안 깬 상태 (WARN 카테고리)."""
    from app.book._swings import find_swings_for_pattern
    swings = find_swings_for_pattern(window, lookback_bars=min(len(window), 80))
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 2:
        return False
    a, b = highs[-2], highs[-1]
    if abs(a.price - b.price) / max(a.price, b.price) > tol:
        return False
    last_close = float(window["close"].iloc[-1])
    # Still ABOVE 10MA (else it's EXIT, not WARN)
    return last_close <= b.price * 1.02


def _is_hns_right_shoulder(window: pd.DataFrame) -> bool:
    """H&S 의 우측 어깨가 형성 중 (10MA 아직 안 깸)."""
    from app.book._swings import find_swings_for_pattern
    swings = find_swings_for_pattern(window, lookback_bars=min(len(window), 100))
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 3:
        return False
    a, c, e = highs[-3], highs[-2], highs[-1]
    if c.price <= a.price or c.price <= e.price:
        return False
    if abs(a.price - e.price) / max(a.price, e.price) > 0.10:
        return False
    return True


def _detect_big_double_bottom(window: pd.DataFrame) -> Optional[Dict]:
    """대쌍바닥 (큰 W) — 책 p288-291 '팔자 고치는 패턴'.

    작은 쌍바닥 두 개가 겹쳐 큰 W 모양을 그리는 구조. 단순화:
      - 긴 윈도우(150~250)에서 쌍바닥 한 번
      - 동일 윈도우 후반부(최근 ~80)에서 또 한 번
      - 후반부 저점이 전반부 저점과 ±8% 근접 → "대쌍"
    """
    if len(window) < 150:
        return None
    long_p = detect_double_bottom(window)
    if long_p is None or long_p.direction != "bullish":
        return None
    short_p = detect_double_bottom(window.tail(min(len(window), 90)))
    if short_p is None:
        return None

    long_lows = long_p.extra or {}
    short_lows = short_p.extra or {}
    l1 = (long_lows.get("low1") or {}).get("price")
    s2 = (short_lows.get("low2") or {}).get("price")
    if not l1 or not s2:
        return None
    spread = abs(l1 - s2) / max(l1, s2)
    if spread > 0.10:
        return None

    return {
        "long": long_p,
        "short": short_p,
        "floor_spread_pct": spread,
        "confidence": min(0.97, max(long_p.confidence, short_p.confidence) + 0.10),
    }


def _detect_hooking_candle(window: pd.DataFrame) -> bool:
    """후킹 캔들: 10MA 아래에 있다가 장대양봉으로 10MA 돌파.

    Book p340: 추세 전환 시작 캔들. (펌핑/랠리 시퀀스는 dolbanji 가 잡음)
    """
    if len(window) < 12:
        return False
    work = add_moving_averages(window, [10])
    if "ma_10" not in work.columns:
        return False
    if work["ma_10"].isna().iloc[-1] or work["ma_10"].isna().iloc[-2]:
        return False
    prev_close = float(work["close"].iloc[-2])
    prev_ma10 = float(work["ma_10"].iloc[-2])
    last_close = float(work["close"].iloc[-1])
    last_open = float(work["open"].iloc[-1])
    last_ma10 = float(work["ma_10"].iloc[-1])
    if not (prev_close < prev_ma10 and last_close > last_ma10):
        return False
    if last_close <= last_open:
        return False
    body = last_close - last_open
    body_avg = (work["close"] - work["open"]).abs().iloc[-21:-1].mean()
    return body_avg > 0 and body >= body_avg * 1.8


def _detect_240ma_anchored_double_bottom(window: pd.DataFrame) -> Optional[Dict]:
    """240MA 가운데 둔 쌍바닥 — 책: '본격 상승' 진입.

    좌측 저점이 240MA 아래, 우측 저점이 240MA 위 (혹은 동등). 240MA 가
    저점들 사이 가격대 안에 위치해야 함.
    """
    if len(window) < 250:
        return None
    db = detect_double_bottom(window)
    if db is None or db.direction != "bullish":
        return None
    extra = db.extra or {}
    l1 = (extra.get("low1") or {}).get("price")
    l2 = (extra.get("low2") or {}).get("price")
    if not l1 or not l2:
        return None
    work = add_moving_averages(window, [240])
    if "ma_240" not in work.columns or work["ma_240"].isna().iloc[-1]:
        return None
    ma240 = float(work["ma_240"].iloc[-1])
    if l1 < ma240 < l2 * 1.02:
        return {"db": db, "ma240": ma240, "low1": l1, "low2": l2,
                "confidence": min(0.95, db.confidence + 0.12)}
    return None


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------
def detect_signals_at(df: pd.DataFrame, i: int) -> SignalSet:
    """한 bar (index i) 시점에서 모든 책 시그널 감지.

    df: full OHLCV (date 컬럼 포함). i: 현재 bar 인덱스.
    오직 df.iloc[:i+1] 만 사용 (룩어헤드 차단).
    """
    if i < 60 or i >= len(df):
        return SignalSet(date=df["date"].iloc[i] if i < len(df) else pd.NaT,
                         close=float(df["close"].iloc[i]) if i < len(df) else 0)

    win = _bar_view(df, i, lookback=300)
    last = win.iloc[-1]
    close = float(last["close"])

    # MA 계산
    ma_work = add_moving_averages(win, [10, 20, 60, 240])
    ma10 = float(ma_work["ma_10"].iloc[-1]) if "ma_10" in ma_work.columns and not np.isnan(ma_work["ma_10"].iloc[-1]) else None
    ma240 = float(ma_work["ma_240"].iloc[-1]) if "ma_240" in ma_work.columns and not np.isnan(ma_work["ma_240"].iloc[-1]) else None

    ss = SignalSet(date=pd.to_datetime(last["date"]),
                   close=close, ma_10=ma10, ma_240=ma240)

    # 거래량 케이스 (한 번 분류, EXIT/WARN/ENTER 에서 재사용)
    try:
        vol_case = classify_volume_case(win)
    except Exception:
        vol_case = None

    # ============================
    # EXIT (최우선) — 10MA 하향 돌파 + 손절 패턴
    # ============================
    if ma10 is not None:
        prev_close = float(win["close"].iloc[-2]) if len(win) >= 2 else close
        prev_ma10 = float(ma_work["ma_10"].iloc[-2]) if len(ma_work) >= 2 and not np.isnan(ma_work["ma_10"].iloc[-2]) else ma10
        # 저승사자 캔들: 10MA 위에서 깨고 내려옴 + 현재 봉 음봉
        if prev_close >= prev_ma10 and close < ma10:
            is_red = close < float(last["open"])
            ss.signals.append(Signal(
                kind="EXIT",
                source="10MA 하향 돌파 (저승사자 캔들)" if is_red
                       else "10MA 하향 돌파",
                confidence=0.90 if is_red else 0.80,
                detail=f"close {close:.2f} < 10MA {ma10:.2f}",
            ))

    # 240MA 아래 돌파 = 죽은 차트 진입
    if ma240 is not None and close < ma240:
        # 직전 봉이 240 위였으면 진짜 이탈
        prev = float(ma_work["ma_240"].iloc[-2]) if len(ma_work) >= 2 and not np.isnan(ma_work["ma_240"].iloc[-2]) else ma240
        if float(win["close"].iloc[-2]) >= prev:
            ss.signals.append(Signal(
                kind="EXIT", source="240MA 하향 이탈 (죽은 차트)",
                confidence=0.95,
                detail=f"close {close:.2f} < 240MA {ma240:.2f}",
            ))

    # 쌍봉 / H&S / 삼고점 완성
    for fn, name in [(detect_double_top, "쌍봉"),
                     (detect_head_and_shoulders, "H&S"),
                     (detect_triple_top, "삼고점")]:
        try:
            p = fn(win)
            if p and p.completed and p.direction == "bearish":
                ss.signals.append(Signal(
                    kind="EXIT", source=f"{name} 완성",
                    confidence=p.confidence,
                    detail=p.reason[:120],
                ))
        except Exception:
            pass

    # 되돌림 패턴 — 하락 (쌍바닥→쌍봉)
    try:
        rev_db_to_dt = detect_reversal_double_bottom_to_top(win)
        if rev_db_to_dt and rev_db_to_dt.completed:
            ss.signals.append(Signal(
                kind="EXIT", source="되돌림 1형 (쌍바닥→쌍봉)",
                confidence=rev_db_to_dt.confidence,
                detail=rev_db_to_dt.reason[:120],
            ))
    except Exception:
        pass

    # 거래량 케이스 11 (죽은 차트) — EXIT 강화 신호
    if vol_case is not None and vol_case.case == 11:
        ss.signals.append(Signal(
            kind="EXIT", source="거래량 케이스 11 (죽은 차트)",
            confidence=vol_case.confidence,
            detail=vol_case.reason[:120],
        ))

    # ============================
    # ENTER — 진입 신호
    # ============================
    entered = False
    pattern_bullish_completed = []
    for fn, name in [(detect_double_bottom, "쌍바닥"),
                     (detect_reverse_head_and_shoulders, "역H&S"),
                     (detect_triple_bottom, "삼중바닥"),
                     (detect_cup_and_handle, "Cup-Handle"),
                     (detect_240ma_breakout, "240MA 돌파"),
                     (detect_dolbanji, "돌반지"),
                     (detect_forking, "포킹")]:
        try:
            p = fn(win)
            if p and p.direction == "bullish":
                pattern_bullish_completed.append(p)
                if p.completed:
                    ss.signals.append(Signal(
                        kind="ENTER", source=f"{name} 완성",
                        confidence=p.confidence,
                        detail=p.reason[:120],
                    ))
                    entered = True
        except Exception:
            pass

    # 4등분선 75% 안전지대 (장대양봉만, 추가 ENTER 시그널)
    if len(win) >= 21:
        cp = CandleParts.from_row(last)
        body_avg = (win["close"] - win["open"]).abs().iloc[-21:-1].mean()
        vol_avg = win["volume"].iloc[-21:-1].mean() if "volume" in win.columns else 0
        if body_avg > 0:
            tags = classify_candle(cp, body_avg, vol_avg)
            if "장대양봉" in tags and quarter_safety(cp) is True:
                ss.signals.append(Signal(
                    kind="ENTER", source="장대양봉 + 75% 안전지대",
                    confidence=0.65,
                    detail="4등분선 75% 위 종가 + 거래량 증가",
                ))

    # 후킹 캔들 (10MA 돌파 장대양봉) — 추세 전환 진입
    try:
        if _detect_hooking_candle(win):
            ss.signals.append(Signal(
                kind="ENTER", source="후킹 캔들 (10MA 돌파)",
                confidence=0.70,
                detail="장대양봉으로 10MA 상향 돌파. 책: 추세 전환 시작.",
            ))
    except Exception:
        pass

    # 역매집 캔들 (역망치 반복 + 바닥 보존)
    try:
        ra = detect_reverse_accumulation(win)
        if ra and ra.get("detected"):
            ss.signals.append(Signal(
                kind="ENTER", source="역매집 캔들 (심봤다)",
                confidence=0.78,
                detail=ra.get("reason", "")[:120],
            ))
    except Exception:
        pass

    # 거래량 케이스 3 (바닥권 거래량 폭증) — 추세 반전 매수
    if vol_case is not None and vol_case.case == 3:
        ss.signals.append(Signal(
            kind="ENTER", source="거래량 케이스 3 (바닥권 폭증)",
            confidence=vol_case.confidence,
            detail=vol_case.reason[:120],
        ))

    # 되돌림 3형 (캔들 하나 반전) — 강한 ENTER
    try:
        rev_single = detect_reversal_single_candle(win)
        if rev_single and rev_single.completed:
            ss.signals.append(Signal(
                kind="ENTER", source="되돌림 3형 (캔들 하나 반전)",
                confidence=rev_single.confidence,
                detail=rev_single.reason[:120],
            ))
    except Exception:
        pass

    # ============================
    # PYRAMID — 강한 상승 / "팔자 고치는 패턴"
    # ============================
    # 짝궁둥이 쌍바닥 (오른쪽 저점 > 왼쪽 저점)
    for p in pattern_bullish_completed:
        if p.kind == "쌍바닥" and p.completed:
            extra = p.extra or {}
            low1 = (extra.get("low1") or {}).get("price")
            low2 = (extra.get("low2") or {}).get("price")
            if low1 and low2 and low2 > low1 * 1.01:
                ss.signals.append(Signal(
                    kind="PYRAMID", source="짝궁둥이 쌍바닥 (오른쪽 높음)",
                    confidence=min(0.95, p.confidence + 0.10),
                    detail=f"L1 {low1:.2f} → L2 {low2:.2f} (책: 최강 매수)",
                ))
        if p.kind == "역H&S" and p.completed:
            # 역H&S 자체가 강한 신호 — 일단 PYRAMID 로도 등록
            ss.signals.append(Signal(
                kind="PYRAMID", source="역H&S 완성 (책: 90%+ 본격 상승)",
                confidence=p.confidence,
                detail=p.reason[:120],
            ))
        if "240MA" in p.kind and p.completed:
            ss.signals.append(Signal(
                kind="PYRAMID", source=f"{p.kind} (책: 옥석 중 옥석)",
                confidence=p.confidence,
                detail=p.reason[:120],
            ))

    # 대쌍바닥 — "팔자 고치는 패턴" (책 p288-291)
    try:
        big_db = _detect_big_double_bottom(win)
        if big_db is not None:
            ss.signals.append(Signal(
                kind="PYRAMID",
                source="대쌍바닥 (팔자 고치는 패턴)",
                confidence=big_db["confidence"],
                detail=f"큰 W 안의 두 쌍바닥, 바닥 차이 {big_db['floor_spread_pct']*100:.1f}%.",
            ))
    except Exception:
        pass

    # 240MA 가운데 둔 쌍바닥 — 본격 상승 진입
    try:
        anchored = _detect_240ma_anchored_double_bottom(win)
        if anchored is not None:
            ss.signals.append(Signal(
                kind="PYRAMID",
                source="240MA 가운데 둔 쌍바닥",
                confidence=anchored["confidence"],
                detail=f"L1 {anchored['low1']:.2f} < 240MA {anchored['ma240']:.2f} < L2 {anchored['low2']:.2f}",
            ))
    except Exception:
        pass

    # 되돌림 1형 (쌍봉→쌍바닥) — 강한 추매
    try:
        rev_dt_to_db = detect_reversal_double_top_to_bottom(win)
        if rev_dt_to_db and rev_dt_to_db.completed:
            ss.signals.append(Signal(
                kind="PYRAMID", source="되돌림 1형 (쌍봉→쌍바닥)",
                confidence=rev_dt_to_db.confidence,
                detail=rev_dt_to_db.reason[:120],
            ))
    except Exception:
        pass

    # 되돌림 2형 (쌍봉→역H&S) — 책: 반드시 진입
    try:
        rev_dt_to_ihs = detect_reversal_double_top_to_inv_hns(win)
        if rev_dt_to_ihs and rev_dt_to_ihs.completed:
            ss.signals.append(Signal(
                kind="PYRAMID", source="되돌림 2형 (쌍봉→역H&S)",
                confidence=rev_dt_to_ihs.confidence,
                detail=rev_dt_to_ihs.reason[:120],
            ))
    except Exception:
        pass

    # 거래량 케이스 7 (급등 중 거래량 감소 = 세력 매집 완료) — 추매
    if vol_case is not None and vol_case.case == 7:
        ss.signals.append(Signal(
            kind="PYRAMID", source="거래량 케이스 7 (매집 완료)",
            confidence=vol_case.confidence,
            detail=vol_case.reason[:120],
        ))

    # ============================
    # WARN — 하락 경고 (아직 EXIT 까지 안 감)
    # ============================
    # 쌍봉 형태 형성 중 (10MA 아직 안 깸)
    if ma10 is not None and close > ma10:
        try:
            if _is_double_top_forming(win):
                ss.signals.append(Signal(
                    kind="WARN", source="쌍봉 형태 형성 (10MA 위)",
                    confidence=0.55,
                    detail="고점 두 번 + 위로 못 뚫음. 다음 봉에서 10MA 깨면 청산.",
                ))
        except Exception:
            pass
        try:
            if _is_hns_right_shoulder(win):
                ss.signals.append(Signal(
                    kind="WARN", source="H&S 우측 어깨 형성",
                    confidence=0.60,
                    detail="머리어깨형 윤곽. 네크라인 하향 시 EXIT.",
                ))
        except Exception:
            pass

    # 4등분선 50% 아래 종가 (양봉이지만 약함)
    if len(win) >= 21:
        cp = CandleParts.from_row(last)
        if cp.is_bullish and cp.range_ > 0:
            close_pct = (cp.close - cp.low) / cp.range_
            if close_pct < 0.50:
                ss.signals.append(Signal(
                    kind="WARN", source="4등분선 50% 아래 종가",
                    confidence=0.40,
                    detail=f"close position {close_pct:.0%} — 추세 약화 가능",
                ))

    # 거래량 케이스 9 (상투권 거래량 증가 = 세력 털기 위험)
    if vol_case is not None and vol_case.case == 9:
        ss.signals.append(Signal(
            kind="WARN", source="거래량 케이스 9 (상투권 폭증)",
            confidence=vol_case.confidence,
            detail=vol_case.reason[:120],
        ))

    # 거래량 케이스 6 (상승 초기 거래량 폭증 = 떠넘기는 자리)
    if vol_case is not None and vol_case.case == 6:
        ss.signals.append(Signal(
            kind="WARN", source="거래량 케이스 6 (상승 초기 폭증)",
            confidence=vol_case.confidence,
            detail=vol_case.reason[:120],
        ))

    return ss
