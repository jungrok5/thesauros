"""Reversal patterns (되돌림 4유형) — 책 p292-301.

저자가 '사부의 비기'라 부르는 4가지:
  1. 동종 패턴 되돌림: 쌍봉 → 쌍바닥 (또는 역방향)
  2. 이종 패턴 되돌림: 쌍봉 → 역H&S (강력)
  3. 캔들 하나로 되돌림: 큰 패턴을 장대양/음봉 1개로 상쇄
  4. 쐐기 수렴: 두 패턴이 쐐기로 모인 후 장대봉 방향 결정

대쌍바닥 / 대쌍봉도 여기 포함 (책 p288-291).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from app.book.patterns import (
    Pattern, detect_double_bottom, detect_double_top,
    detect_reverse_head_and_shoulders, detect_head_and_shoulders,
)


def _opposite_window(df: pd.DataFrame, recent_pat: Pattern,
                     window: int) -> pd.DataFrame:
    """Return the slice of df that is BEFORE recent_pat.detected_at minus a tail."""
    if "date" not in df.columns:
        return df.iloc[:-window] if len(df) > window else df
    cutoff_idx = df.index[-1] - window
    return df.iloc[:max(0, cutoff_idx)]


def detect_reversal_double_top_to_bottom(df: pd.DataFrame,
                                         lookback: int = 200) -> Optional[Pattern]:
    """되돌림 1패턴 (동종): 직전 쌍봉을 쌍바닥으로 되돌림 → 상승.

    Book p294-295: HLB글로벌 +71% 사례.
    """
    if df is None or len(df) < lookback:
        return None
    # 후반부에 쌍바닥
    last_window = df.tail(lookback // 2)
    db = detect_double_bottom(last_window)
    if db is None:
        return None
    # 그 직전(전반부)에 쌍봉
    prior_window = df.tail(lookback).head(lookback // 2 + 30)
    dt = detect_double_top(prior_window)
    if dt is None:
        return None

    conf = min(0.93, (db.confidence + dt.confidence) / 2 + 0.10)
    return Pattern(
        kind="되돌림 1형 (쌍봉→쌍바닥)",
        direction="bullish",
        confidence=conf,
        completed=db.completed,
        detected_at=db.detected_at,
        entry=db.entry,
        stop=db.stop,
        target=db.target * 1.1 if db.target else None,
        reason="직전 쌍봉(하락 에너지) → 쌍바닥(반전) → 상승. 책: 사부의 비기.",
        extra={"double_top": dt.to_dict(), "double_bottom": db.to_dict()},
    )


def detect_reversal_double_bottom_to_top(df: pd.DataFrame,
                                         lookback: int = 200) -> Optional[Pattern]:
    """되돌림 1패턴 (동종 반대): 쌍바닥을 쌍봉으로 → 하락 가속.

    Book p295: 강력한 하락 신호 (모든 보유 매도 + 인버스).
    """
    if df is None or len(df) < lookback:
        return None
    last_window = df.tail(lookback // 2)
    dt = detect_double_top(last_window)
    if dt is None:
        return None
    prior_window = df.tail(lookback).head(lookback // 2 + 30)
    db = detect_double_bottom(prior_window)
    if db is None:
        return None

    conf = min(0.93, (dt.confidence + db.confidence) / 2 + 0.10)
    return Pattern(
        kind="되돌림 1형 (쌍바닥→쌍봉)",
        direction="bearish",
        confidence=conf,
        completed=dt.completed,
        detected_at=dt.detected_at,
        entry=dt.entry,
        stop=dt.stop,
        target=dt.target * 1.1 if dt.target else None,
        reason="쌍바닥 상승 에너지를 쌍봉으로 상쇄. 책: 인버스 진입 자리.",
        extra={"double_bottom": db.to_dict(), "double_top": dt.to_dict()},
    )


def detect_reversal_double_top_to_inv_hns(df: pd.DataFrame,
                                          lookback: int = 220) -> Optional[Pattern]:
    """되돌림 2패턴 (이종): 쌍봉 → 역H&S. 책: 쌍바닥보다 훨씬 강력."""
    if df is None or len(df) < lookback:
        return None
    last_window = df.tail(lookback // 2 + 20)
    hns = detect_reverse_head_and_shoulders(last_window)
    if hns is None:
        return None
    prior_window = df.tail(lookback).head(lookback // 2 + 30)
    dt = detect_double_top(prior_window)
    if dt is None:
        return None

    conf = min(0.95, max(hns.confidence, dt.confidence) + 0.07)
    return Pattern(
        kind="되돌림 2형 (쌍봉→역H&S)",
        direction="bullish",
        confidence=conf,
        completed=hns.completed,
        detected_at=hns.detected_at,
        entry=hns.entry,
        stop=hns.stop,
        target=hns.target,
        reason="쌍봉을 역H&S로 되돌림 — 책: 쌍바닥보다 훨씬 강력, 반드시 진입.",
        extra={"double_top": dt.to_dict(), "reverse_hns": hns.to_dict()},
    )


def detect_reversal_single_candle(df: pd.DataFrame,
                                  lookback: int = 100) -> Optional[Pattern]:
    """되돌림 3패턴: 패턴을 캔들 하나로 되돌림 (장대양봉 1개).

    Book p297-299: 나스닥 2023-01 사례. 거래량 폭증 + 매크로 이벤트 동반.
    """
    if df is None or len(df) < lookback:
        return None

    last_window = df.tail(lookback // 2)
    dt = detect_double_top(last_window)
    if dt is None or not dt.completed:
        return None

    # Look for a recent single bullish bar that closes well above the death cross point
    work = df.tail(20).reset_index(drop=True)
    body = (work["close"] - work["open"]).abs()
    body_avg = body.iloc[:-1].mean() if len(body) > 1 else 0
    last = work.iloc[-1]
    if body_avg <= 0:
        return None
    if last["close"] - last["open"] < body_avg * 3:
        return None  # need 3x average body
    if last["close"] < last["open"]:
        return None
    # Volume confirmation
    vol_avg = work["volume"].iloc[:-1].mean() if "volume" in work.columns else 0
    high_vol = vol_avg > 0 and last["volume"] > vol_avg * 2.5

    conf = 0.80
    if high_vol:
        conf += 0.10
    conf = min(conf, 0.95)

    return Pattern(
        kind="되돌림 3형 (캔들 하나 반전)",
        direction="bullish",
        confidence=conf,
        completed=True,
        detected_at=pd.to_datetime(last["date"] if "date" in last else df["date"].iloc[-1]),
        entry=float(last["close"]),
        stop=float(last["low"] * 0.97),
        target=float(last["close"] * 1.15),
        reason=(
            "직전 쌍봉/저승사자 캔들을 단일 장대양봉이 한번에 상쇄. "
            "책: 강력한 매집 세력 존재. 매크로 이벤트 동반 시 본격 상승."
        ),
        extra={"prior_double_top": dt.to_dict(),
               "body_x_avg": round(float((last["close"] - last["open"]) / body_avg), 1),
               "high_volume": bool(high_vol)},
    )


def detect_all_reversals(df: pd.DataFrame) -> List[Pattern]:
    out: List[Pattern] = []
    for fn in [
        detect_reversal_double_top_to_bottom,
        detect_reversal_double_bottom_to_top,
        detect_reversal_double_top_to_inv_hns,
        detect_reversal_single_candle,
    ]:
        try:
            p = fn(df)
        except Exception:
            p = None
        if p is not None:
            out.append(p)
    out.sort(key=lambda p: -p.confidence)
    return out
