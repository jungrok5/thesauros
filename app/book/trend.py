"""Trend analysis (1부 3장 + 2부 3-4장).

책의 핵심 추세 판정 규칙:
  - 월봉 10이평선 = 가장 명확한 기준선 ("진정한 추세선")
  - 주봉 10이평선 = 보조 기준선
  - 가격 > 10MA → 상방 (HOLD/BUY 가능)
  - 가격 < 10MA → 하방 (SELL/회피)
  - 정배열: price > MA5 > MA10 > MA20 > MA60 > MA120 > MA240
  - 역배열: 반대 순서 — "사망유희의 사망탑", 매수 금지

추세선 작도:
  - 책은 꼬리→몸통 작도를 추천하지만,
    여기서는 "눈에 보이는 추세선=이평선"을 우선시 (책의 권장).
  - 직접 그리는 추세선은 P2에서 swing low/high 기반 회귀로 보조 구현.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


MA_PERIODS = [5, 10, 20, 60, 120, 240]


def resample_to_period(df: pd.DataFrame, period: str = "W") -> pd.DataFrame:
    """Daily OHLCV → weekly ('W') or monthly ('M') candles.

    df must have columns: date (or DatetimeIndex), open, high, low, close, volume.
    Returns DataFrame indexed by period-end date.
    """
    d = df.copy()
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date")
    d.index = pd.to_datetime(d.index)

    rule = {"W": "W-FRI", "M": "ME"}[period]
    agg = d.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(how="all")
    if "adj_close" in d.columns:
        agg["adj_close"] = d["adj_close"].resample(rule).last()
    return agg


def add_moving_averages(df: pd.DataFrame, periods: List[int] = None,
                        price_col: str = "close") -> pd.DataFrame:
    """Compute rolling MAs.

    Bars-shortage policy (2026-05-19 honesty pass):
      - Short MAs (≤ 60 bars): min_periods = p // 3 so 5MA/10MA/20MA/60MA
        emit early — book룰에서 단기 MA는 추세 시작부터 의미 있음.
      - Long MAs (> 60 bars, esp. 240MA): min_periods = p * 2/3.
        Otherwise a US ticker with only 110 weeks of Naver-sourced
        bars would emit a "240MA" that's actually just a 110-week mean
        — misrepresenting the book's structural cycle anchor (p324).
        Now `ma_240` stays NULL until we have ≥ 160 weeks (~3 years),
        and the analyzer's score-rescale path handles the absence
        explicitly (trend.py L195-201).
    """
    periods = periods or MA_PERIODS
    out = df.copy()
    for p in periods:
        if p > 60:
            min_periods = max(1, int(p * 2 / 3))
        else:
            min_periods = max(1, p // 3)
        out[f"ma_{p}"] = out[price_col].rolling(
            window=p, min_periods=min_periods,
        ).mean()
    return out


@dataclass
class TrendState:
    """Snapshot of trend status for one timeframe.

    Bool fields are convenient for the UI; the score combines them into [-1, 1].
    """
    timeframe: str               # "daily" / "weekly" / "monthly"
    price: float
    ma_10: float
    above_ma_10: bool            # 가격이 10MA 위? (책의 핵심 1차 필터)
    ma_10_slope_up: bool         # 10MA 자체가 우상향?
    ma_240: Optional[float]
    above_ma_240: Optional[bool] # 240MA 위? (책의 '죽은 차트' 여부)
    alignment_score: float       # 정배열 점수 [-1, 1]
    overall_score: float         # 종합 점수 [-1, 1]
    label: str                   # "강세" / "약세" / "혼조" / "데드"


def alignment_score(mas: List[float]) -> float:
    """Return [-1, 1] alignment score.

    Input mas must be in order [MA5, MA10, MA20, MA60, MA120, MA240].
    +1 = perfect 정배열 (단기 > 장기), -1 = perfect 역배열.
    """
    mas = [m for m in mas if m is not None and not np.isnan(m)]
    if len(mas) < 2:
        return 0.0
    n_pairs = len(mas) - 1
    inversions = sum(1 if mas[i] > mas[i + 1] else -1
                     for i in range(n_pairs))
    return inversions / n_pairs


def is_sideways(df: pd.DataFrame, lookback: int = 40,
                range_pct_max: float = 0.12) -> bool:
    """혼조(박스권) 추세 감지 — 책: 박스권에선 매매 금지.

    최근 lookback 봉의 (high - low) / mean(close) 비율이 작으면 박스권.
    """
    if df is None or len(df) < lookback:
        return False
    tail = df.tail(lookback)
    hi = float(tail["high"].max())
    lo = float(tail["low"].min())
    avg = float(tail["close"].mean())
    if avg <= 0:
        return False
    return (hi - lo) / avg < range_pct_max


def is_bearish_alignment(df: pd.DataFrame,
                          periods: Optional[List[int]] = None,
                          threshold: float = -0.50) -> bool:
    """역배열 감지 — 책: 역배열 종목 매수 금지 (사망탑).

    alignment_score 가 threshold 이하면 역배열로 간주.
    """
    periods = periods or [5, 10, 20, 60, 120, 240]
    if df is None or len(df) < max(periods):
        return False
    work = add_moving_averages(df, periods)
    last = work.iloc[-1]
    mas = []
    for p in periods:
        v = last.get(f"ma_{p}")
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        mas.append(float(v))
    if len(mas) < 3:
        return False
    return alignment_score(mas) <= threshold


def classify_trend_type(df: pd.DataFrame, lookback: int = 60) -> str:
    """추세 3종류 분류 — 책 3장.

    returns: 'uptrend' / 'downtrend' / 'sideways' / 'unknown'
    """
    if df is None or len(df) < lookback:
        return "unknown"
    if is_sideways(df, lookback=min(lookback, 40)):
        return "sideways"
    tail = df.tail(lookback)
    chg = (float(tail["close"].iloc[-1]) - float(tail["close"].iloc[0])) / float(tail["close"].iloc[0])
    if chg > 0.10:
        return "uptrend"
    if chg < -0.10:
        return "downtrend"
    return "sideways"


def classify_trend(df: pd.DataFrame, timeframe: str) -> Optional[TrendState]:
    """Run book's trend rules on a daily/weekly/monthly OHLC frame.

    Returns None if there aren't enough rows (need at least 10 bars for 10MA).
    """
    if df is None or len(df) < 10:
        return None
    work = add_moving_averages(df)
    last = work.iloc[-1]

    price = float(last["close"])
    ma_10 = float(last.get("ma_10", np.nan))
    if np.isnan(ma_10):
        return None

    # 10MA slope: compare last vs 5 bars ago
    ma_10_slope_up = False
    if len(work) >= 5:
        prev_ma10 = work["ma_10"].iloc[-5]
        if not np.isnan(prev_ma10):
            ma_10_slope_up = bool(ma_10 > prev_ma10)

    ma_240 = float(last.get("ma_240", np.nan)) if "ma_240" in work.columns else None
    above_ma_240: Optional[bool]
    if ma_240 is None or np.isnan(ma_240):
        ma_240 = None
        above_ma_240 = None
    else:
        above_ma_240 = bool(price > ma_240)

    above_ma_10 = bool(price > ma_10)

    mas = [float(last.get(f"ma_{p}", np.nan)) for p in MA_PERIODS]
    align = alignment_score(mas)

    # Combine into overall score
    score = 0.0
    score += 0.35 * (1.0 if above_ma_10 else -1.0)
    score += 0.15 * (1.0 if ma_10_slope_up else -0.5)
    score += 0.30 * align
    if above_ma_240 is not None:
        score += 0.20 * (1.0 if above_ma_240 else -1.0)
    else:
        score *= 1.25  # rescale if 240MA missing (short history)
    score = max(-1.0, min(1.0, score))

    if score > 0.5:
        label = "강세"
    elif score < -0.5:
        label = "약세" if above_ma_240 != False else "데드"
        # 240MA 아래 + 강한 약세 = "죽은 차트"
        if above_ma_240 is False and score < -0.7:
            label = "데드"
    else:
        label = "혼조"

    return TrendState(
        timeframe=timeframe,
        price=price,
        ma_10=ma_10,
        above_ma_10=above_ma_10,
        ma_10_slope_up=ma_10_slope_up,
        ma_240=None if (ma_240 is None or np.isnan(ma_240)) else ma_240,
        above_ma_240=above_ma_240,
        alignment_score=align,
        overall_score=score,
        label=label,
    )


@dataclass
class MultiTrend:
    """Combined daily + weekly + monthly trend assessment."""
    daily: Optional[TrendState]
    weekly: Optional[TrendState]
    monthly: Optional[TrendState]
    book_signal: str             # "BUY" / "HOLD" / "SELL" / "AVOID"
    book_reason: str             # human-readable narrative

    def to_dict(self) -> Dict:
        def _td(t):
            if t is None:
                return None
            return {
                "timeframe": t.timeframe,
                "price": round(t.price, 4),
                "ma_10": round(t.ma_10, 4),
                "above_ma_10": t.above_ma_10,
                "ma_10_slope_up": t.ma_10_slope_up,
                "ma_240": (round(t.ma_240, 4) if t.ma_240 else None),
                "above_ma_240": t.above_ma_240,
                "alignment_score": round(t.alignment_score, 3),
                "overall_score": round(t.overall_score, 3),
                "label": t.label,
            }
        return {
            "daily": _td(self.daily),
            "weekly": _td(self.weekly),
            "monthly": _td(self.monthly),
            "book_signal": self.book_signal,
            "book_reason": self.book_reason,
        }


def analyze_multi_timeframe(
    df: pd.DataFrame, input_grain: str = "D",
) -> MultiTrend:
    """Run trend analysis on daily, weekly, and monthly views.

    Book's rule:
      - 월봉 10MA 위 + 주봉 10MA 위 → BUY (강세 추세 살아있음)
      - 월봉 10MA 위 만 → HOLD (조정 중일 가능성)
      - 월봉 10MA 아래 → SELL (추세 사망, 무조건 청산)
      - 240MA 아래 = 죽은 차트 → AVOID

    `input_grain`:
      "D" — `df` is daily; resample to W/M as before (KR path).
      "W" — `df` is already weekly (US path via Naver, which caps daily
            at 110 rows but allows ~2y weekly). Skip daily classifier
            entirely; treat the input as weekly; resample weekly→monthly.
            The book's primary signal (월봉 240MA + 월봉/주봉 10MA) survives
            because monthly is still reconstructable from weekly.
    """
    if input_grain == "W":
        daily = None
        weekly = classify_trend(df, "weekly")
        monthly_df = resample_to_period(df, "M")
        monthly = classify_trend(monthly_df, "monthly")
    else:
        daily = classify_trend(df, "daily")
        weekly_df = resample_to_period(df, "W")
        weekly = classify_trend(weekly_df, "weekly")
        monthly_df = resample_to_period(df, "M")
        monthly = classify_trend(monthly_df, "monthly")

    # Apply book's signal logic
    parts: List[str] = []
    signal = "HOLD"

    if monthly is None:
        signal = "HOLD"
        parts.append("월봉 데이터 부족")
    elif monthly.above_ma_240 is False:
        signal = "AVOID"
        parts.append("월봉 240MA 아래 = 죽은 차트 (책: 매수 금지)")
    elif monthly.above_ma_10 is False:
        signal = "SELL"
        parts.append("월봉 10MA 하향 이탈 → 추세 사망 (책: 무조건 청산)")
    elif weekly is None or weekly.above_ma_10:
        # 월봉 10MA 위 + 주봉 10MA 위 (또는 주봉 정보 없음) = 강세
        if weekly is not None and weekly.alignment_score > 0.5 and monthly.alignment_score > 0:
            signal = "BUY"
            parts.append("월봉/주봉 10MA 위 + 정배열 → 추세 살아있음")
        else:
            signal = "HOLD"
            parts.append("월봉 10MA 위 → 추세 유효, 정배열은 미확정")
    else:
        signal = "HOLD"
        parts.append("월봉 10MA 위지만 주봉 10MA 이탈 → 단기 조정")

    if monthly and monthly.above_ma_240:
        parts.append("월봉 240MA 위 = 강한 지지 자리")
    if weekly and weekly.alignment_score >= 0.8:
        parts.append(f"주봉 정배열({weekly.alignment_score:.2f})")
    if daily and daily.alignment_score >= 0.8:
        parts.append(f"일봉 정배열({daily.alignment_score:.2f})")

    return MultiTrend(
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        book_signal=signal,
        book_reason=" / ".join(parts),
    )
