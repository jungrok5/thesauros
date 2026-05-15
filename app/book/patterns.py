"""Pattern detection (2부 2장 + 일부 4장).

상승 패턴 4개:
  1. 쌍바닥 (Double Bottom, W자)
  2. 역H&S  (Reverse Head & Shoulders)
  3. 삼중바닥 (Triple Bottom)
  4. 원형바닥 + Cup with Handle (William O'Neil)

하락 패턴 4개:
  1. 쌍봉 (Double Top, M자)
  2. H&S
  3. 삼고점 (Triple Top)
  4. 원형천장 (Rounding Top, 거의 안 씀 — 10MA 깨짐만 검사)

특이 패턴:
  5. 240MA 돌파매매 (책: 돌파매매의 옥석 중 옥석)
  6. 돌반지 패턴 (돌파-지지-반등)

Each detector returns a `Pattern` with:
  - kind: pattern name (kr label)
  - confidence: 0-1
  - entry, stop, target prices (per book's rules)
  - reason: short Korean explanation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.book._swings import Swing, find_swings, find_swings_for_pattern
from app.book.trend import add_moving_averages, MA_PERIODS


@dataclass
class Pattern:
    """One detected chart pattern."""
    kind: str
    direction: str           # "bullish" or "bearish"
    confidence: float        # 0-1
    completed: bool          # True if entry signal fully formed
    detected_at: pd.Timestamp
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    reason: str = ""
    extra: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "confidence": round(self.confidence, 3),
            "completed": bool(self.completed),
            "detected_at": str(
                self.detected_at.date() if hasattr(self.detected_at, "date")
                else self.detected_at
            ),
            "entry": (round(self.entry, 4) if self.entry else None),
            "stop": (round(self.stop, 4) if self.stop else None),
            "target": (round(self.target, 4) if self.target else None),
            "reason": self.reason,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _within(a: float, b: float, tol: float) -> bool:
    """|a - b| / max(|a|, |b|) <= tol  (relative diff within tol)."""
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base <= tol


def _ma_value(df: pd.DataFrame, period: int) -> Optional[float]:
    if len(df) < period:
        return None
    return float(df["close"].rolling(period).mean().iloc[-1])


# ---------------------------------------------------------------------------
# 1. 쌍바닥 (Double Bottom)
# ---------------------------------------------------------------------------
def detect_double_bottom(df: pd.DataFrame, lookback: int = 120,
                         tol: float = 0.05) -> Optional[Pattern]:
    """W자: 두 저점이 비슷한 가격대, 중간 반등, 마지막 10MA 돌파(완성).

    Book p254-257:
      - 전저점 지키기 (왼쪽 저점 < 오른쪽 저점 시가 기준)
      - 2차 브레이킹 거래량 = 1차의 70~200%
      - 10MA 돌파 후킹 캔들 → 패턴 완성
      - 짝궁둥이 쌍바닥 (오른쪽이 더 높음) = 가장 강력
    """
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    lows = [s for s in swings if s.kind == "low"]
    if len(lows) < 2:
        return None

    last_two = lows[-2:]
    a, b = last_two[0], last_two[1]

    # Filter: must be similar prices (book: 전저점 안 깨짐)
    if not _within(a.price, b.price, tol):
        return None
    if b.price < a.price * 0.97:
        # right bottom broke prior low → not a valid double bottom
        return None

    # Right bottom must come after a peak between them
    between = [s for s in swings if a.idx < s.idx < b.idx]
    peaks = [s for s in between if s.kind == "high"]
    if not peaks:
        return None
    peak = max(peaks, key=lambda s: s.price)
    neckline = peak.price

    last_close = float(df["close"].iloc[-1])
    last_idx = len(df) - 1
    ma_10 = _ma_value(df, 10)

    # Completion: 10MA hookline candle
    completed = ma_10 is not None and last_close > ma_10 and last_close > b.price * 1.02

    # Confidence — base + adjustments
    conf = 0.55
    if b.price > a.price * 1.005:
        conf += 0.20  # 짝궁둥이 (오른쪽 높음)
    if b.volume > 0 and a.volume > 0 and 0.7 <= (b.volume / a.volume) <= 2.0:
        conf += 0.10
    if completed:
        conf += 0.10
    conf = min(conf, 0.95)

    # Entry/stop/target per book
    entry = neckline if not completed else last_close
    stop = min(a.price, b.price) * 0.97
    target = entry + (entry - min(a.price, b.price))

    return Pattern(
        kind="쌍바닥",
        direction="bullish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[last_idx]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=entry,
        stop=stop,
        target=target,
        reason=(
            f"쌍바닥: L1={a.price:.2f}@{a.date.date()} → L2={b.price:.2f}@{b.date.date()}"
            + (" (짝궁둥이형, 책의 최강 매수)" if b.price > a.price * 1.005 else "")
            + (" / 10MA 돌파 완성" if completed else " / 미완 (네크라인 미돌파)")
        ),
        extra={"low1": a.to_dict(), "low2": b.to_dict(), "neckline": neckline},
    )


# ---------------------------------------------------------------------------
# 2. 쌍봉 (Double Top)
# ---------------------------------------------------------------------------
def detect_double_top(df: pd.DataFrame, lookback: int = 120,
                      tol: float = 0.05) -> Optional[Pattern]:
    """M자: 두 고점이 비슷, 10MA 하향 돌파 시 완성 (저승사자 캔들).

    Book p260-263:
      - 두 번째 거래량은 첫 번째보다 적어야 함
      - 10MA 하향 돌파 음봉 = 패턴 완성 (즉시 청산)
    """
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 2:
        return None

    last_two = highs[-2:]
    a, b = last_two[0], last_two[1]
    if not _within(a.price, b.price, tol):
        return None

    between = [s for s in swings if a.idx < s.idx < b.idx]
    troughs = [s for s in between if s.kind == "low"]
    if not troughs:
        return None
    valley = min(troughs, key=lambda s: s.price)
    neckline = valley.price

    last_close = float(df["close"].iloc[-1])
    ma_10 = _ma_value(df, 10)
    completed = ma_10 is not None and last_close < ma_10 and last_close < neckline

    conf = 0.60
    if b.volume > 0 and a.volume > 0 and b.volume < a.volume:
        conf += 0.15  # 책 규칙: 거래량 감소
    if completed:
        conf += 0.10
    conf = min(conf, 0.95)

    entry = last_close if completed else neckline
    stop = max(a.price, b.price) * 1.03
    target = neckline - (max(a.price, b.price) - neckline)

    return Pattern(
        kind="쌍봉",
        direction="bearish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[-1]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=entry,
        stop=stop,
        target=target,
        reason=(
            f"쌍봉: H1={a.price:.2f}@{a.date.date()} → H2={b.price:.2f}@{b.date.date()}"
            + (" / 10MA 하향 돌파 (저승사자 캔들 발생 → 무조건 청산)" if completed
               else " / 미완")
        ),
        extra={"high1": a.to_dict(), "high2": b.to_dict(), "neckline": neckline},
    )


# ---------------------------------------------------------------------------
# 3. H&S (Head & Shoulders, 하락)
# ---------------------------------------------------------------------------
def detect_head_and_shoulders(df: pd.DataFrame, lookback: int = 150,
                              tol: float = 0.05) -> Optional[Pattern]:
    """A-B-C-D-E: 좌어깨-골-머리-골-우어깨. 머리가 가장 높고 어깨 거의 같음.

    Book p266-269:
      - C(머리) > A(좌어깨), E(우어깨) ≤ A
      - 거래량: A > C > E
      - 네크라인 (B,D 잇는 선) 하향 돌파 시 완성
    """
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 3 or len(lows) < 2:
        return None

    # Try the last 3 highs as left/head/right
    a, c, e = highs[-3], highs[-2], highs[-1]
    if c.price <= a.price or c.price <= e.price:
        return None  # head not the highest
    if not _within(a.price, e.price, tol * 1.5):
        return None  # shoulders not similar

    # Pick the two lows between A and E to form neckline
    between_lows = [s for s in lows if a.idx < s.idx < e.idx]
    if len(between_lows) < 2:
        return None
    b, d = between_lows[0], between_lows[-1]
    # Neckline = linear interpolation y(last) between (b.idx,b.price) and (d.idx,d.price)
    if d.idx == b.idx:
        neckline = (b.price + d.price) / 2
    else:
        slope = (d.price - b.price) / (d.idx - b.idx)
        last_idx = len(df) - 1
        neckline = b.price + slope * (last_idx - b.idx)

    last_close = float(df["close"].iloc[-1])
    completed = last_close < neckline

    # Volume check (책: A 큼 > C 감소 > E 더 감소)
    conf = 0.55
    if a.volume > c.volume > e.volume > 0:
        conf += 0.20
    if completed:
        conf += 0.15
    conf = min(conf, 0.95)

    head_h = c.price - neckline
    target = neckline - head_h

    return Pattern(
        kind="H&S (머리어깨형)",
        direction="bearish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[-1]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=last_close if completed else neckline,
        stop=c.price * 1.02,
        target=target,
        reason=(
            f"H&S: L={a.price:.2f} H={c.price:.2f} R={e.price:.2f} / "
            f"네크라인 {neckline:.2f}"
            + (" / 네크라인 하향 돌파 = 완성, 인버스 진입 자리" if completed else " / 미완")
        ),
        extra={
            "left_shoulder": a.to_dict(),
            "head": c.to_dict(),
            "right_shoulder": e.to_dict(),
            "neckline": neckline,
            "min_objective": target,
        },
    )


# ---------------------------------------------------------------------------
# 4. 역H&S (Reverse Head & Shoulders, 상승)
# ---------------------------------------------------------------------------
def detect_reverse_head_and_shoulders(df: pd.DataFrame, lookback: int = 150,
                                      tol: float = 0.05) -> Optional[Pattern]:
    """역H&S = H&S 거꾸로. 책 p269-271: 신뢰도 0.90, 90%+ 본격 상승."""
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(lows) < 3 or len(highs) < 2:
        return None

    a, c, e = lows[-3], lows[-2], lows[-1]
    if c.price >= a.price or c.price >= e.price:
        return None
    if not _within(a.price, e.price, tol * 1.5):
        return None

    between_highs = [s for s in highs if a.idx < s.idx < e.idx]
    if len(between_highs) < 2:
        return None
    b, d = between_highs[0], between_highs[-1]
    if d.idx == b.idx:
        neckline = (b.price + d.price) / 2
    else:
        slope = (d.price - b.price) / (d.idx - b.idx)
        last_idx = len(df) - 1
        neckline = b.price + slope * (last_idx - b.idx)

    last_close = float(df["close"].iloc[-1])
    completed = last_close > neckline

    conf = 0.65          # 책: 역H&S는 쌍바닥보다 훨씬 강력
    if a.volume < c.volume < e.volume:
        conf += 0.15     # 책 핵심: 저점마다 거래량 증가
    if completed:
        conf += 0.15
    conf = min(conf, 0.97)

    head_h = neckline - c.price
    target = neckline + head_h

    return Pattern(
        kind="역H&S",
        direction="bullish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[-1]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=last_close if completed else neckline,
        stop=c.price * 0.97,
        target=target,
        reason=(
            f"역H&S: 머리 {c.price:.2f} (가장 낮음), 어깨 {a.price:.2f}/{e.price:.2f}"
            + (" / 네크라인 상향 돌파 = 완성 (책: 90%+ 본격 상승)" if completed else " / 미완")
        ),
        extra={
            "head": c.to_dict(),
            "left_shoulder": a.to_dict(),
            "right_shoulder": e.to_dict(),
            "neckline": neckline,
            "target": target,
        },
    )


# ---------------------------------------------------------------------------
# 5. 삼중바닥 (Triple Bottom)
# ---------------------------------------------------------------------------
def detect_triple_bottom(df: pd.DataFrame, lookback: int = 180,
                         tol: float = 0.05) -> Optional[Pattern]:
    """세 저점이 비슷한 가격대. 거래량 우상향이면 강력 매수.

    Book p276-279: SAMG엔터 450% 사례 (저점이 점차 상승 = 더 강력)
    """
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    lows = [s for s in swings if s.kind == "low"]
    if len(lows) < 3:
        return None

    a, b, c = lows[-3], lows[-2], lows[-1]
    if not (_within(a.price, b.price, tol) and _within(b.price, c.price, tol)):
        return None

    # 책 권장: 거래량 우상향, 저점도 점차 상승
    rising_bottoms = a.price <= b.price <= c.price
    rising_volume = a.volume < b.volume < c.volume if all([a.volume, b.volume, c.volume]) else False

    ma_10 = _ma_value(df, 10)
    last_close = float(df["close"].iloc[-1])
    completed = ma_10 is not None and last_close > ma_10

    conf = 0.70
    if rising_bottoms:
        conf += 0.10
    if rising_volume:
        conf += 0.10
    if completed:
        conf += 0.07
    conf = min(conf, 0.97)

    # Find peak between for stop reference
    peaks = [s for s in swings if a.idx < s.idx < c.idx and s.kind == "high"]
    target_base = max(p.price for p in peaks) if peaks else last_close * 1.10
    floor = min(a.price, b.price, c.price)

    return Pattern(
        kind="삼중바닥",
        direction="bullish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[-1]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=last_close if completed else target_base,
        stop=floor * 0.97,
        target=target_base + (target_base - floor),
        reason=(
            f"삼중바닥: {a.price:.2f}, {b.price:.2f}, {c.price:.2f}"
            + (" / 저점 우상향" if rising_bottoms else "")
            + (" + 거래량 우상향" if rising_volume else "")
            + (" / 10MA 돌파" if completed else " / 미완")
        ),
        extra={"bottoms": [a.to_dict(), b.to_dict(), c.to_dict()]},
    )


# ---------------------------------------------------------------------------
# 6. 삼고점 (Triple Top)
# ---------------------------------------------------------------------------
def detect_triple_top(df: pd.DataFrame, lookback: int = 180,
                      tol: float = 0.05) -> Optional[Pattern]:
    """세 고점이 비슷. 거래량 점차 감소 → 끝장 신호 (책 p273-275)."""
    if df is None or len(df) < lookback:
        return None

    swings = find_swings_for_pattern(df, lookback)
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 3:
        return None

    a, b, c = highs[-3], highs[-2], highs[-1]
    if not (_within(a.price, b.price, tol) and _within(b.price, c.price, tol)):
        return None

    falling_volume = (
        a.volume > b.volume > c.volume
        if all([a.volume, b.volume, c.volume]) else False
    )
    ma_10 = _ma_value(df, 10)
    last_close = float(df["close"].iloc[-1])
    completed = ma_10 is not None and last_close < ma_10

    conf = 0.75
    if falling_volume:
        conf += 0.15
    if completed:
        conf += 0.07
    conf = min(conf, 0.97)

    ceiling = max(a.price, b.price, c.price)
    troughs = [s for s in swings if a.idx < s.idx < c.idx and s.kind == "low"]
    floor = min(t.price for t in troughs) if troughs else last_close * 0.9

    return Pattern(
        kind="삼고점",
        direction="bearish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(df["date"].iloc[-1]) if "date" in df.columns else pd.to_datetime(df.index[-1]),
        entry=last_close if completed else floor,
        stop=ceiling * 1.03,
        target=floor - (ceiling - floor),
        reason=(
            f"삼고점: {a.price:.2f}, {b.price:.2f}, {c.price:.2f}"
            + (" + 거래량 감소" if falling_volume else "")
            + " (책: 끝장 신호)"
            + (" / 10MA 하향 돌파" if completed else " / 미완")
        ),
        extra={"tops": [a.to_dict(), b.to_dict(), c.to_dict()]},
    )


# ---------------------------------------------------------------------------
# 7. Cup with Handle (원형바닥 + 손잡이, 윌리엄 오닐)
# ---------------------------------------------------------------------------
def detect_cup_and_handle(df: pd.DataFrame,
                          cup_min_bars: int = 60,
                          cup_max_bars: int = 260,
                          tol: float = 0.05) -> Optional[Pattern]:
    """깊은 U자 + 우측 작은 V자 (handle), 핸들 위로 돌파 시 진입.

    Book p280-281: 삼성전자 사례. 240MA 동시 돌파 시 더 강력.
    """
    if df is None or len(df) < cup_min_bars + 10:
        return None

    work = df.tail(cup_max_bars + 30).reset_index(drop=True)
    if len(work) < cup_min_bars + 10:
        return None

    swings = find_swings(work)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 1:
        return None

    # Find a cup: leftmost high and rightmost high (matching), low between
    last_high = highs[-1]
    candidates_left = [h for h in highs[:-1] if last_high.idx - h.idx >= cup_min_bars]
    if not candidates_left:
        return None
    left_high = max(candidates_left, key=lambda h: h.price)
    if not _within(left_high.price, last_high.price, tol * 2):
        return None
    cup_bottom = min((s for s in lows if left_high.idx < s.idx < last_high.idx),
                     key=lambda s: s.price, default=None)
    if cup_bottom is None:
        return None
    if cup_bottom.price > min(left_high.price, last_high.price) * 0.90:
        return None  # not deep enough

    # Handle: short shallow pullback after last_high
    handle_zone = work.iloc[last_high.idx:].reset_index(drop=True)
    if len(handle_zone) < 3:
        return None
    handle_low = float(handle_zone["low"].min())
    handle_depth = (last_high.price - handle_low) / last_high.price
    if handle_depth > 0.15:
        return None  # too deep, handle invalid

    last_close = float(work["close"].iloc[-1])
    rim = last_high.price
    completed = last_close > rim

    conf = 0.70
    ma_240 = _ma_value(work, 240)
    if ma_240 is not None and last_close > ma_240 and rim > ma_240:
        conf += 0.10
    if completed:
        conf += 0.15
    conf = min(conf, 0.95)

    cup_depth = rim - cup_bottom.price

    return Pattern(
        kind="원형바닥 (Cup with Handle)",
        direction="bullish",
        confidence=conf,
        completed=completed,
        detected_at=pd.to_datetime(work["date"].iloc[-1]) if "date" in work.columns else pd.to_datetime(work.index[-1]),
        entry=rim,
        stop=handle_low * 0.97,
        target=rim + cup_depth,  # 책: 컵 깊이만큼 추가 상승
        reason=(
            f"Cup-Handle: rim {rim:.2f}, bottom {cup_bottom.price:.2f} "
            f"({(cup_depth/rim*100):.1f}% deep), handle {handle_depth*100:.1f}% pullback"
            + (" / 핸들 돌파 완성" if completed else " / 핸들 진행 중")
        ),
        extra={
            "left_high": left_high.to_dict(),
            "cup_bottom": cup_bottom.to_dict(),
            "right_high": last_high.to_dict(),
            "handle_low": handle_low,
            "rim": rim,
        },
    )


# ---------------------------------------------------------------------------
# 8. 240MA 돌파매매 (책의 옥석 중 옥석)
# ---------------------------------------------------------------------------
def detect_240ma_breakout(df: pd.DataFrame, lookback_below: int = 60,
                          tol: float = 0.10) -> Optional[Pattern]:
    """240이평선 밑에서 따개비처럼 붙어 있다가 양봉으로 돌파.

    Book p350-353: 피에스케이홀딩스 +388%, 디아이씨 +160% 사례.
    Criteria:
      - Last N bars mostly within ±tol of 240MA
      - Most recent bar is bullish + closes above 240MA
      - Pumping volume should be low (책: 매물 소화 끝남)
    """
    if df is None or len(df) < 240 + lookback_below + 5:
        return None

    work = add_moving_averages(df, [240]).copy().reset_index(drop=True)
    if work["ma_240"].iloc[-1] is None or np.isnan(work["ma_240"].iloc[-1]):
        return None

    ma240 = float(work["ma_240"].iloc[-1])
    last_close = float(work["close"].iloc[-1])
    last_open = float(work["open"].iloc[-1])
    last_high = float(work["high"].iloc[-1])
    last_volume = float(work["volume"].iloc[-1]) if "volume" in work.columns else 0.0

    # Did we break out (close above 240MA from below)?
    prev_closes = work["close"].iloc[-lookback_below-1:-1]
    prev_ma240 = work["ma_240"].iloc[-lookback_below-1:-1]
    below_count = (prev_closes < prev_ma240).sum()
    proximity_count = (
        (prev_closes < prev_ma240 * (1 + tol))
        & (prev_closes > prev_ma240 * (1 - tol * 2))
    ).sum()

    # 띠개비처럼 붙음
    barnacle = (
        below_count >= lookback_below * 0.55
        and proximity_count >= lookback_below * 0.45
    )

    crossed = work["close"].iloc[-2] < work["ma_240"].iloc[-2] and last_close > ma240
    bullish = last_close > last_open
    if not (crossed and bullish):
        return None

    # Volume check (책: 돌파 거래량 적을수록 매집 완료)
    vol_avg_60 = float(work["volume"].iloc[-61:-1].mean()) if "volume" in work.columns else 0
    quiet_volume = vol_avg_60 > 0 and last_volume < vol_avg_60 * 1.5

    conf = 0.75
    if barnacle:
        conf += 0.10
    if quiet_volume:
        conf += 0.08    # 책: 거래량 없는 돌파 = 옥석
    if last_close > ma240 * 1.02:
        conf += 0.05    # 강한 돌파
    conf = min(conf, 0.97)

    return Pattern(
        kind="240MA 돌파매매",
        direction="bullish",
        confidence=conf,
        completed=True,
        detected_at=pd.to_datetime(work["date"].iloc[-1]) if "date" in work.columns else pd.to_datetime(work.index[-1]),
        entry=last_close,
        stop=ma240 * 0.97,
        target=last_close + (last_close - ma240 * 0.95) * 5,  # 책 사례 +160~+388% 기준 큰 보유
        reason=(
            f"240MA {ma240:.2f} 상향 돌파 양봉 (close {last_close:.2f})"
            + (" / 따개비형 다지기 후 돌파 (책의 옥석)" if barnacle else "")
            + (" / 돌파 거래량 적음 = 매집 완료" if quiet_volume else "")
        ),
        extra={"ma_240": ma240, "barnacle": bool(barnacle),
               "quiet_volume": bool(quiet_volume)},
    )


# ---------------------------------------------------------------------------
# 9. 돌반지 패턴 (돌파-지지-반등)
# ---------------------------------------------------------------------------
def detect_dolbanji(df: pd.DataFrame, ma_period: int = 240,
                    lookback: int = 30) -> Optional[Pattern]:
    """이평선 돌파 후 그 이평선의 지지를 받고 다시 반등.

    Book p344-345:
      - 돌파 (후킹 캔들) → 지지 (펌핑 캔들, 거래량↓) → 반등 (랠리 캔들)
      - 240MA에서 가장 강력, 10MA에서도 적용 가능
    """
    if df is None or len(df) < ma_period + lookback:
        return None

    work = add_moving_averages(df, [10, ma_period]).copy().reset_index(drop=True)
    if work[f"ma_{ma_period}"].isna().iloc[-1]:
        return None

    last_n = work.tail(lookback).reset_index(drop=True)
    ma_col = f"ma_{ma_period}"

    # Step 1: detect breakout within lookback (close crossed above ma)
    crossed_indices = [
        i for i in range(1, len(last_n))
        if last_n["close"].iloc[i-1] < last_n[ma_col].iloc[i-1]
        and last_n["close"].iloc[i] > last_n[ma_col].iloc[i]
    ]
    if not crossed_indices:
        return None
    breakout_i = crossed_indices[-1]

    # Step 2: pullback to MA (지지)
    post = last_n.iloc[breakout_i+1:]
    if post.empty:
        return None
    touched = (post["low"] <= post[ma_col] * 1.01).any()
    if not touched:
        return None
    # 거래량 적음 동안 지지
    vol_avg = work["volume"].iloc[-lookback*2:-lookback].mean() if "volume" in work.columns else 0
    pullback_vols = post["volume"].values if "volume" in post.columns else []
    quiet_pullback = (
        vol_avg > 0 and len(pullback_vols) > 0
        and pullback_vols.mean() < vol_avg * 0.9
    )

    # Step 3: 반등 (마지막 봉이 양봉 + close가 ma 위)
    last_close = float(last_n["close"].iloc[-1])
    last_open = float(last_n["open"].iloc[-1])
    last_ma = float(last_n[ma_col].iloc[-1])
    rebound = last_close > last_open and last_close > last_ma
    if not rebound:
        return None

    conf = 0.75
    if quiet_pullback:
        conf += 0.10
    if ma_period == 240:
        conf += 0.05
    conf = min(conf, 0.95)

    return Pattern(
        kind=f"돌반지 ({ma_period}MA)",
        direction="bullish",
        confidence=conf,
        completed=True,
        detected_at=pd.to_datetime(work["date"].iloc[-1]) if "date" in work.columns else pd.to_datetime(work.index[-1]),
        entry=last_close,
        stop=last_ma * 0.97,
        target=last_close + (last_close - last_ma) * 3,
        reason=(
            f"돌반지: {ma_period}MA 돌파-지지-반등 시퀀스 완성"
            + (" / 펌핑 구간 거래량 적음" if quiet_pullback else "")
        ),
        extra={"ma_period": ma_period, "ma_value": last_ma},
    )


# ---------------------------------------------------------------------------
# 10. 포킹 (Forking) — 이평선 수렴 후 장대양봉 돌파
# ---------------------------------------------------------------------------
def detect_forking(df: pd.DataFrame, periods: List[int] = None,
                   spread_max: float = 0.03,
                   body_mult: float = 1.8) -> Optional[Pattern]:
    """여러 이평선이 한 점에 수렴 + 강한 양봉이 그 점을 뚫음.

    Book p336-339.
    """
    periods = periods or [5, 10, 20, 60]
    if df is None or len(df) < max(periods) + 5:
        return None

    work = add_moving_averages(df, periods).copy().reset_index(drop=True)
    mas = [float(work[f"ma_{p}"].iloc[-1]) for p in periods]
    if any(np.isnan(v) for v in mas):
        return None

    spread = (max(mas) - min(mas)) / np.mean(mas)
    if spread > spread_max:
        return None

    last_close = float(work["close"].iloc[-1])
    last_open = float(work["open"].iloc[-1])
    body = abs(last_close - last_open)
    body_avg = (work["close"] - work["open"]).abs().iloc[-21:-1].mean()
    if body_avg <= 0 or body < body_avg * body_mult:
        return None
    if last_close <= last_open:
        return None  # must be bullish
    if last_close <= max(mas):
        return None

    aligned = all(mas[i] >= mas[i+1] for i in range(len(mas) - 1))

    conf = 0.78
    if aligned:
        conf += 0.10
    conf = min(conf, 0.95)

    return Pattern(
        kind="포킹",
        direction="bullish",
        confidence=conf,
        completed=True,
        detected_at=pd.to_datetime(work["date"].iloc[-1]) if "date" in work.columns else pd.to_datetime(work.index[-1]),
        entry=last_close,
        stop=min(mas) * 0.97,
        target=last_close + body * 2,
        reason=(
            f"포킹: MA{periods} 수렴 (spread {spread*100:.1f}%) + 장대양봉 돌파"
            + (" / 정배열" if aligned else "")
        ),
        extra={"ma_spread_pct": round(spread * 100, 2),
               "mas": {p: round(v, 4) for p, v in zip(periods, mas)}},
    )


# ---------------------------------------------------------------------------
# 11. 눌림목 매매 (책 4장 p340-345: "고수는 음봉 매수, 하수는 양봉 추격")
# ---------------------------------------------------------------------------
def detect_pullback_buy(df: pd.DataFrame,
                         ma_period: int = 20,
                         lookback: int = 40,
                         max_pullback_pct: float = 0.10) -> Optional[Pattern]:
    """눌림목 매매 — 정배열 상승 추세 + 단기 음봉 조정 + 이평선 지지.

    Book: 음봉에 매수, 양봉 추격 금지. 거래량 적은 조정 = 매집 완료 임박.

    Criteria:
      1. 직전 60봉이 상승 추세 (close 끝 > close 시작)
      2. 가격이 ma_period (10/20/60) 위에 있다가 살짝 눌림 (-3 ~ -10%)
      3. 이번 봉이 음봉 (close < open)
      4. 이번 봉의 low 가 ma_period 에 1% 이내 접근
      5. 거래량이 직전 20봉 평균보다 작음 (매집 완료 조용함)
    """
    if df is None or len(df) < lookback + ma_period:
        return None

    # Only compute the ma we need (was [10,20,60] = 3 rolling means).
    ma_col = f"ma_{ma_period}"
    work = add_moving_averages(df, [ma_period]).copy().reset_index(drop=True)
    if ma_col not in work.columns or pd.isna(work[ma_col].iloc[-1]):
        return None

    last = work.iloc[-1]
    last_close = float(last["close"])
    last_open = float(last["open"])
    last_low = float(last["low"])
    ma_val = float(last[ma_col])

    # 1. 큰 추세 = 상승
    seg = work.tail(lookback)
    seg_chg = (float(seg["close"].iloc[-1]) - float(seg["close"].iloc[0])) / float(seg["close"].iloc[0])
    if seg_chg < 0.05:
        return None

    # 2. 직전 (lookback - 10) 동안 가격이 ma 위에 있었음
    pre = work.iloc[-lookback:-3]
    above_ratio = (pre["close"] > pre[ma_col]).mean()
    if above_ratio < 0.70:
        return None

    # 최근 고점 대비 눌림 강도
    recent_high = float(work["close"].iloc[-15:].max())
    pullback = (recent_high - last_close) / recent_high
    if pullback <= 0 or pullback > max_pullback_pct:
        return None

    # 3. 이번 봉이 음봉
    if last_close >= last_open:
        return None

    # 4. low 가 ma 에 접근 (지지 테스트)
    if abs(last_low - ma_val) / ma_val > 0.015:
        return None

    # 5. 거래량 조용함
    vol_avg = work["volume"].iloc[-21:-1].mean() if "volume" in work.columns else 0
    last_vol = float(last["volume"]) if "volume" in work.columns else 0
    quiet = vol_avg > 0 and last_vol < vol_avg * 0.85

    conf = 0.72
    if quiet:
        conf += 0.08
    if pullback > 0.05:
        conf += 0.05
    if ma_period >= 60:
        conf += 0.05
    conf = min(conf, 0.95)

    return Pattern(
        kind=f"눌림목 매매 ({ma_period}MA)",
        direction="bullish",
        confidence=conf,
        completed=True,
        detected_at=pd.to_datetime(last["date"] if "date" in last else work.index[-1]),
        entry=last_close,
        stop=ma_val * 0.97,
        target=last_close + (last_close - ma_val) * 4,
        reason=(
            f"눌림목: {ma_period}MA 지지 + 음봉 매수 ({pullback*100:.1f}% 눌림)"
            + (" / 거래량 조용 (매집 완료)" if quiet else "")
            + ". 책: 음봉 매수, 양봉 추격 금지."
        ),
        extra={"ma_period": ma_period, "pullback_pct": float(pullback),
               "quiet_volume": bool(quiet)},
    )


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
def detect_all(df: pd.DataFrame) -> List[Pattern]:
    """Run every pattern detector and return non-None results."""
    detectors = [
        detect_double_bottom,
        detect_double_top,
        detect_head_and_shoulders,
        detect_reverse_head_and_shoulders,
        detect_triple_bottom,
        detect_triple_top,
        detect_cup_and_handle,
        detect_240ma_breakout,
        detect_dolbanji,
        detect_forking,
    ]
    out: List[Pattern] = []
    for fn in detectors:
        try:
            p = fn(df)
        except Exception:
            p = None
        if p is not None:
            out.append(p)
    out.sort(key=lambda p: (-p.confidence, p.kind))
    return out
