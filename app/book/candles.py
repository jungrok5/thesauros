"""Candle analysis (2부 1장).

책의 5대 분석기 + 4등분선 75% 안전지대 + 캔들 종류 분류.

4등분선 (책의 시그니처 기법, p220-221):
  - 캔들의 (high - low)를 4등분
  - 종가가 75%~100% 구간 (= low + 0.75*(high-low) 이상) → "안전지대"
  - 다음 봉 상승 확률 책 주장 ~75%
  - 50% 아래 종가 = 추세 약화

캔들 종류:
  - 장대양봉/장대음봉: body가 평균의 2배 이상
  - 망치형/역망치형: 한쪽 꼬리가 몸통의 2배 이상
  - 도지: body가 (high-low)의 10% 이하
  - 눈썹 캔들: body 작고 두 꼬리 비슷
  - 후킹 캔들: 장대양봉 + 10MA 돌파  (trend 모듈과 결합 필요)
  - 펌핑 캔들: 작은 도지/눈썹, 후킹 직후 1~3봉, 거래량 적음
  - 랠리 캔들: 펌핑 직후 본격 상승 장대양봉
  - 저승사자 캔들: 10MA 하향 돌파 장대음봉
  - 역매집 캔들: 긴 위꼬리 + 작은 몸통 (역망치 형태) 반복
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class CandleParts:
    """Geometric breakdown of one OHLC bar."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    body: float                  # |close - open|
    upper_wick: float            # high - max(open, close)
    lower_wick: float            # min(open, close) - low
    range_: float                # high - low
    is_bullish: bool             # close > open
    body_pct: float              # body / range_
    upper_pct: float
    lower_pct: float
    close_position: float        # (close - low) / range_  ∈ [0, 1]

    @classmethod
    def from_row(cls, row) -> "CandleParts":
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        v = float(row.get("volume", 0))
        rng = max(h - l, 1e-9)
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        return cls(
            open=o, high=h, low=l, close=c, volume=v,
            body=body,
            upper_wick=upper,
            lower_wick=lower,
            range_=h - l,
            is_bullish=c > o,
            body_pct=body / rng,
            upper_pct=upper / rng,
            lower_pct=lower / rng,
            close_position=(c - l) / rng if rng > 0 else 0.5,
        )


def quarter_safety(c: CandleParts, level: float = 0.75) -> Optional[bool]:
    """4등분선 (75%) 안전지대 판정.

    Returns:
        True  — 양봉 + 종가가 (low + level*range) 이상 (책: 다음 봉 상승 확률 高)
        False — 양봉이지만 종가가 그 아래
        None  — 음봉 (적용 X)
    """
    if not c.is_bullish:
        return None
    if c.range_ <= 0:
        return False
    threshold = c.low + level * c.range_
    return bool(c.close >= threshold)


def quarter_zone(reference_bar_low: float, reference_bar_close: float,
                 current_price: float) -> str:
    """4등분선 zone of `current_price` against a reference bullish bar's
    body (book p218-223 — the signature "4등분선 기법").

    The book divides a 장대양봉's body (open..close) into quarters.
    Subsequent price action is interpreted by which quarter the price
    has retraced into:

        ≥75% (안전지대): book says 다음 봉 상승 확률 75%. Treat as buy / add.
        50%~75%        : soft warning, still alive.
        25%~50%        : 매입원가 영역, red flag.
        <25%           : 절대 자리 깨짐 — bullish bar is "dead", sell.

    Args:
        reference_bar_low: the bullish reference bar's OPEN (not low —
            we measure body, not range; book is explicit p221).
        reference_bar_close: the same bar's close.
        current_price: today's close.

    Returns one of "safe75" / "warn50" / "danger25" / "broken".
    Returns "n/a" if the reference is non-bullish or zero-body.
    """
    body = reference_bar_close - reference_bar_low
    if body <= 0:
        return "n/a"
    pos = (current_price - reference_bar_low) / body
    if pos >= 0.75:
        return "safe75"
    if pos >= 0.50:
        return "warn50"
    if pos >= 0.25:
        return "danger25"
    return "broken"


def classify_candle(c: CandleParts, body_avg: float, vol_avg: float,
                    prev_close: Optional[float] = None) -> List[str]:
    """Classify a candle into one or more book categories.

    body_avg, vol_avg = recent rolling averages (e.g., 20-bar) used for "large" detection.
    prev_close = previous bar's close, used for 갭상승/갭하락 detection (book p230-233).

    Returns:
        List of classification tags (a candle may have multiple, e.g.
        '장대양봉' + '구라캔들').
    """
    tags: List[str] = []

    # 도지 — body very small (widened threshold to 12% so near-doji
    # candles like body 0.10–0.12 still register as the indecision
    # signal the book treats them as).
    if c.body_pct < 0.12:
        if c.upper_pct > 0.5 and c.lower_pct < 0.15:
            tags.append("그레이브스톤도지")
        elif c.lower_pct > 0.5 and c.upper_pct < 0.15:
            tags.append("드래곤플라이도지")
        else:
            tags.append("도지")

    # 망치형 / 역망치형 — long single-side wick rejecting price.
    # Old rule required `other_wick < 0.15` (too strict — a body-14%
    # candle with lower-wick 68% and upper-wick 18% was missed entirely
    # for 국보디자인 2026-05-22). Relax to "dominant wick is at least
    # 2× the body AND at least 1.5× the other wick".
    elif (
        c.lower_pct >= 2 * c.body_pct
        and c.lower_pct >= 1.5 * max(c.upper_pct, 0.01)
        and c.lower_pct >= 0.35
    ):
        tags.append("망치형" if c.is_bullish else "교수형")
    elif (
        c.upper_pct >= 2 * c.body_pct
        and c.upper_pct >= 1.5 * max(c.lower_pct, 0.01)
        and c.upper_pct >= 0.35
    ):
        tags.append("역망치형" if c.is_bullish else "유성형")

    # 눈썹 캔들: small body + both wicks roughly equal (spinning top).
    # If we already tagged 망치/역망치 (asymmetric), this branch is
    # skipped by the elif chain.
    elif c.body_pct < 0.35 and c.upper_pct > 0.20 and c.lower_pct > 0.20:
        tags.append("눈썹캔들")

    # 장대 양/음봉 — body significantly larger than recent average
    if body_avg > 0 and c.body >= body_avg * 2.0:
        tags.append("장대양봉" if c.is_bullish else "장대음봉")

    # 구라캔들 (book p214-215): 큰 봉인데 거래량 부족 = 가짜 신호.
    # Book example was 장대음봉, but the principle is symmetric — any
    # big-bodied candle that prints below average volume is suspect.
    if (
        c.body_pct >= 0.6
        and vol_avg > 0
        and c.volume < vol_avg * 0.7
    ):
        tags.append("구라캔들")

    # Legacy heuristic kept for compat — strict "no upper wick + 장대양봉":
    if c.is_bullish and "장대양봉" in tags and c.upper_pct < 0.05:
        tags.append("구라캔들의심")

    # 양팔봉 (book p247-248): 위·아래 꼬리 모두 큼 + 작은 몸통.
    # Direction undecided — wait for next bar.
    if (
        c.body_pct < 0.3
        and c.upper_pct >= 0.25
        and c.lower_pct >= 0.25
    ):
        tags.append("양팔봉")

    # 주고받고 (book p250): handled at higher level (needs prior bar);
    # 은둔형 장대양봉 (p249): 3-bar cumulative gain — also needs prior bars.
    # Both surfaced as analyzer-level helpers below.

    # 갭 (book p230-233): 시가 위치 신호.
    if prev_close is not None and prev_close > 0:
        gap = (c.open - prev_close) / prev_close
        if gap >= 0.01:
            tags.append("갭상승")
        elif gap <= -0.01:
            tags.append("갭하락")

    # Volume spike
    if vol_avg > 0 and c.volume >= vol_avg * 2.0:
        tags.append("대거래")

    return tags


@dataclass
class CandleAnalysis:
    """Per-bar enriched analysis used by patterns + UI."""
    date: pd.Timestamp
    parts: CandleParts
    body_avg_20: float           # 20-bar average body
    vol_avg_20: float            # 20-bar average volume
    tags: List[str] = field(default_factory=list)
    in_safe_zone: Optional[bool] = None  # 4등분선 75% (양봉만)

    def to_dict(self) -> Dict:
        p = self.parts
        return {
            "date": str(self.date.date() if hasattr(self.date, "date") else self.date),
            "open": round(p.open, 4),
            "high": round(p.high, 4),
            "low": round(p.low, 4),
            "close": round(p.close, 4),
            "volume": int(p.volume),
            "body_pct": round(p.body_pct, 3),
            "upper_wick_pct": round(p.upper_pct, 3),
            "lower_wick_pct": round(p.lower_pct, 3),
            "close_position": round(p.close_position, 3),
            "is_bullish": p.is_bullish,
            "tags": self.tags,
            "in_safe_zone_75": self.in_safe_zone,
        }


def analyze_candles(df: pd.DataFrame, window: int = 20) -> List[CandleAnalysis]:
    """Run candle classification across all bars in df.

    df must contain: date (index or column), open, high, low, close, volume.
    Returns list of CandleAnalysis, one per bar.
    """
    work = df.copy()
    if "date" not in work.columns:
        work = work.reset_index().rename(columns={"index": "date"})
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").reset_index(drop=True)

    # Rolling averages of body size and volume (excluding current bar)
    body = (work["close"] - work["open"]).abs()
    body_avg = body.shift(1).rolling(window, min_periods=max(1, window // 2)).mean()
    vol_avg = work["volume"].shift(1).rolling(window, min_periods=max(1, window // 2)).mean()

    out: List[CandleAnalysis] = []
    for i, row in work.iterrows():
        parts = CandleParts.from_row(row)
        ba = float(body_avg.iloc[i]) if not np.isnan(body_avg.iloc[i]) else 0.0
        va = float(vol_avg.iloc[i]) if not np.isnan(vol_avg.iloc[i]) else 0.0
        prev_close = (
            float(work["close"].iloc[i - 1]) if i > 0 else None
        )
        tags = classify_candle(parts, ba, va, prev_close=prev_close)
        safe = quarter_safety(parts)
        out.append(CandleAnalysis(
            date=row["date"],
            parts=parts,
            body_avg_20=ba,
            vol_avg_20=va,
            tags=tags,
            in_safe_zone=safe,
        ))
    return out


def latest_candle_summary(df: pd.DataFrame, window: int = 20) -> Optional[Dict]:
    """Convenience: classify only the most recent bar for fast UI lookups."""
    series = analyze_candles(df.tail(max(window + 5, 30)), window=window)
    if not series:
        return None
    return series[-1].to_dict()
