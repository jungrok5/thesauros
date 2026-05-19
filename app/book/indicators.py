"""RSI + MACD with book-faithful interpretation.

The book (캔들차트 추세추종) treats RSI/MACD as **second-class** signals:
they're allowed to corroborate or contradict price/candle/volume, never
to override them. So this module's output isn't a stand-alone trade
signal — it's structured context that the verdict / summary table
overlays with the primary analysis.

Conventions:
  - Weekly bars (the post-pivot canonical timeframe).
  - RSI: Wilder's smoothing, 14-period (the standard).
  - MACD: 12/26 EMAs, 9-EMA signal line (the standard).
  - All thresholds match common practice unless the book contradicts.

Output schema (IndicatorSnapshot.to_dict()):
  {
    "rsi": 56.3,
    "rsi_zone": "neutral",       # oversold (<30) / weak (30-45) /
                                 # neutral (45-55) / strong (55-70) /
                                 # overbought (>70)
    "rsi_interpretation": "...", # one-liner with book context
    "macd": 1.84,
    "macd_signal": 1.42,
    "macd_hist": 0.42,
    "macd_state": "golden",      # golden / dead / pending_golden /
                                 # pending_dead / flat
    "macd_divergence": "bearish", # bullish / bearish / none — vs price
                                 # over last 16 weeks
    "macd_interpretation": "...",
  }

The book's primary signal is always price + 10MA + 240MA. RSI/MACD just
tell you whether momentum is corroborating or fighting the trend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Standard textbook calculations
# ----------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Pure-gain windows (no losses) map to RSI=100;
    pure-loss windows map to RSI=0 (not NaN — that's the textbook
    convention)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    out = pd.Series(np.nan, index=series.index)
    mask = avg_loss > 0
    # Normal case: RS = avg_gain / avg_loss → RSI in (0, 100)
    rs_normal = avg_gain[mask] / avg_loss[mask]
    out.loc[mask] = 100 - (100 / (1 + rs_normal))
    # No-loss windows where avg_gain > 0 → RSI = 100
    no_loss = (avg_loss == 0) & (avg_gain > 0)
    out.loc[no_loss] = 100.0
    # No-gain no-loss (perfectly flat) → 50 (neutral) per convention
    flat = (avg_loss == 0) & (avg_gain == 0)
    out.loc[flat] = 50.0
    return out.clip(0, 100)


def macd(series: pd.Series,
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> pd.DataFrame:
    """Standard MACD: 12/26 EMAs + 9-EMA signal line.
    Returns DataFrame with columns: macd, signal, hist."""
    ema_fast = series.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = series.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    sig_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({
        "macd": macd_line,
        "signal": sig_line,
        "hist": macd_line - sig_line,
    })


# ----------------------------------------------------------------------
# Zones / state / book-context interpretation
# ----------------------------------------------------------------------

def _rsi_zone(v: float) -> str:
    if np.isnan(v):
        return "n/a"
    if v < 30:
        return "oversold"
    if v < 45:
        return "weak"
    if v <= 55:
        return "neutral"
    if v <= 70:
        return "strong"
    return "overbought"


def _macd_state(macd_now: float, sig_now: float,
                macd_prev: float, sig_prev: float) -> str:
    """One of golden / dead / pending_golden / pending_dead / flat."""
    if any(np.isnan(x) for x in (macd_now, sig_now, macd_prev, sig_prev)):
        return "n/a"
    crossed_up = macd_prev <= sig_prev and macd_now > sig_now
    crossed_down = macd_prev >= sig_prev and macd_now < sig_now
    if crossed_up:
        return "golden"
    if crossed_down:
        return "dead"
    if macd_now > sig_now:
        # Above signal, not freshly crossed — durable trend
        gap_now = macd_now - sig_now
        gap_prev = macd_prev - sig_prev
        if gap_now < gap_prev:
            return "pending_dead"
        return "strong"
    # Below signal
    gap_now = sig_now - macd_now
    gap_prev = sig_prev - macd_prev
    if gap_now < gap_prev:
        return "pending_golden"
    return "weak"


def _macd_divergence(closes: pd.Series, hist: pd.Series,
                     lookback: int = 16) -> str:
    """Detect divergence between price and MACD histogram.

    Bearish: price makes higher high, hist makes lower high → 매수세 약화.
    Bullish: price makes lower low, hist makes higher low → 매도세 약화.

    Lookback default 16 bars (~4 months on weekly). Returns
    "bullish" / "bearish" / "none".
    """
    n = lookback
    if len(closes) < n or len(hist) < n:
        return "n/a"
    recent_closes = closes.tail(n)
    recent_hist = hist.tail(n)
    # Latest pivot vs the one before it (simple two-extremes test).
    # We compare the latest local high/low vs an earlier high/low.
    half = n // 2
    early_closes = recent_closes.iloc[:half]
    late_closes = recent_closes.iloc[half:]
    early_hist = recent_hist.iloc[:half]
    late_hist = recent_hist.iloc[half:]

    if late_closes.max() > early_closes.max() and late_hist.max() < early_hist.max():
        return "bearish"
    if late_closes.min() < early_closes.min() and late_hist.min() > early_hist.min():
        return "bullish"
    return "none"


# ----------------------------------------------------------------------
# Book-faithful narrative
# ----------------------------------------------------------------------

def _rsi_narrative(zone: str, rsi_value: float,
                   trend_label: Optional[str]) -> str:
    """Map RSI zone × current trend → book-context sentence.

    Book treats RSI as corroboration:
      - oversold + 추세 강세 = 정상 조정 (책: 단기 눌림목 매수 자리 후보)
      - overbought + 추세 강세 = 추세 살아있지만 단기 과열
      - oversold + 추세 약세 = 그냥 약세 지속 (책: 절대 매수 X)
      - overbought + 추세 약세 = N자 탈출 가능성 vs 단기 반등
    """
    if zone == "n/a":
        return "RSI 데이터 부족"
    bullish_trend = trend_label in ("강세",)
    if zone == "oversold":
        if bullish_trend:
            return f"RSI {rsi_value:.0f} (oversold) — 추세 강세에서의 단기 눌림목. 책: 후킹 캔들 대기 자리"
        return f"RSI {rsi_value:.0f} (oversold) — 추세 약세 + 과매도. 책: 반전 캔들 확정까지 매수 X"
    if zone == "weak":
        return f"RSI {rsi_value:.0f} (약세권) — 매수세 부족"
    if zone == "neutral":
        return f"RSI {rsi_value:.0f} (중립) — 방향성 약함"
    if zone == "strong":
        if bullish_trend:
            return f"RSI {rsi_value:.0f} (강세권) — 추세 모멘텀 정상"
        return f"RSI {rsi_value:.0f} (강세권) — 약세 추세 속 단기 반등"
    # overbought
    if bullish_trend:
        return f"RSI {rsi_value:.0f} (overbought) — 추세 살아있지만 단기 과열. 책: 위꼬리/도지 반전 봉 주시"
    return f"RSI {rsi_value:.0f} (overbought) — N자 탈출 시도 vs 단기 반등 한계"


def _macd_narrative(state: str, divergence: str,
                    macd_value: float, hist_value: float,
                    trend_label: Optional[str]) -> str:
    if state == "n/a":
        return "MACD 데이터 부족"
    bullish_trend = trend_label in ("강세",)
    bits: list[str] = []
    state_label = {
        "golden": "🟢 골든크로스 (이번 봉)",
        "dead": "🔴 데드크로스 (이번 봉)",
        "strong": "MACD > 시그널 (상승 모멘텀 유지)",
        "weak": "MACD < 시그널 (하락 모멘텀 유지)",
        "pending_golden": "골든크로스 임박 (간격 좁아짐)",
        "pending_dead": "데드크로스 임박 (간격 좁아짐)",
    }.get(state, state)
    bits.append(state_label)
    if state == "golden":
        if bullish_trend:
            bits.append("책: 후킹 캔들 + 골든크로스 = 강한 매수 신호 corroboration")
        else:
            bits.append("책: 약세 추세 속 골든크로스 = 1차 브레이킹 가능성 (확정 X)")
    elif state == "dead":
        if bullish_trend:
            bits.append("책: 강세 추세 속 데드크로스 = 저승사자 캔들 corroboration, 청산 검토")
        else:
            bits.append("책: 약세 추세 + 데드크로스 = 하락 지속 확정")
    if divergence == "bearish":
        bits.append("⚠ 약세 다이버전스 — 가격 신고가, MACD 저점 (매수세 약화)")
    elif divergence == "bullish":
        bits.append("✅ 강세 다이버전스 — 가격 신저점, MACD 고점 (매도세 소진)")
    return " · ".join(bits)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

@dataclass
class IndicatorSnapshot:
    rsi: Optional[float]
    rsi_zone: str
    rsi_interpretation: str
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    macd_state: str
    macd_divergence: str
    macd_interpretation: str

    def to_dict(self) -> Dict:
        def _r(v: Optional[float], digits: int = 2) -> Optional[float]:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return None
            return round(float(v), digits)

        return {
            "rsi": _r(self.rsi),
            "rsi_zone": self.rsi_zone,
            "rsi_interpretation": self.rsi_interpretation,
            "macd": _r(self.macd, 4),
            "macd_signal": _r(self.macd_signal, 4),
            "macd_hist": _r(self.macd_hist, 4),
            "macd_state": self.macd_state,
            "macd_divergence": self.macd_divergence,
            "macd_interpretation": self.macd_interpretation,
        }


def compute_indicators(df: pd.DataFrame,
                       trend_label: Optional[str] = None
                       ) -> Optional[IndicatorSnapshot]:
    """Build the snapshot from weekly closes.

    Returns None when there isn't enough history (need ≥ 35 bars for
    MACD to print a meaningful value; ≥ 14 bars for RSI).
    """
    if df is None or len(df) < 35 or "close" not in df.columns:
        return None
    closes = df["close"].astype(float)
    rsi_series = rsi(closes, period=14)
    macd_df = macd(closes, fast=12, slow=26, signal=9)

    rsi_now = float(rsi_series.iloc[-1]) if len(rsi_series) else float("nan")
    rsi_zone = _rsi_zone(rsi_now)
    rsi_narr = _rsi_narrative(rsi_zone, rsi_now, trend_label)

    macd_now = float(macd_df["macd"].iloc[-1]) if len(macd_df) else float("nan")
    sig_now = float(macd_df["signal"].iloc[-1]) if len(macd_df) else float("nan")
    hist_now = float(macd_df["hist"].iloc[-1]) if len(macd_df) else float("nan")
    macd_prev = (
        float(macd_df["macd"].iloc[-2]) if len(macd_df) >= 2 else float("nan")
    )
    sig_prev = (
        float(macd_df["signal"].iloc[-2]) if len(macd_df) >= 2 else float("nan")
    )
    state = _macd_state(macd_now, sig_now, macd_prev, sig_prev)
    divergence = _macd_divergence(closes, macd_df["hist"])
    macd_narr = _macd_narrative(
        state, divergence, macd_now, hist_now, trend_label,
    )

    return IndicatorSnapshot(
        rsi=rsi_now if not np.isnan(rsi_now) else None,
        rsi_zone=rsi_zone,
        rsi_interpretation=rsi_narr,
        macd=macd_now if not np.isnan(macd_now) else None,
        macd_signal=sig_now if not np.isnan(sig_now) else None,
        macd_hist=hist_now if not np.isnan(hist_now) else None,
        macd_state=state,
        macd_divergence=divergence,
        macd_interpretation=macd_narr,
    )
