"""Swing-point detection used by pattern modules.

A "swing high" is a local high that's higher than all bars within `prominence_bars`
on both sides. Same idea for "swing low". This is the foundation for every
pattern in the book (쌍바닥, H&S, 삼중바닥, 추세선, etc.).

We use a fractal-style detector tuned for daily/weekly/monthly book analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


@dataclass
class Swing:
    """One swing high or low."""
    idx: int                # row index into source df
    date: pd.Timestamp
    price: float
    kind: str               # "high" or "low"
    volume: float = 0.0

    def to_dict(self) -> dict:
        return {
            "idx": int(self.idx),
            "date": str(self.date.date() if hasattr(self.date, "date") else self.date),
            "price": round(float(self.price), 4),
            "kind": self.kind,
            "volume": float(self.volume),
        }


def find_swings(df: pd.DataFrame, distance: int = 5,
                use_wick: bool = True) -> List[Swing]:
    """Return all swing highs + lows in chronological order.

    Args:
        df: must have columns date, open, high, low, close, volume.
        distance: minimum bars between swings on the same side.
        use_wick: True → use high/low (wick) for extreme detection
                  False → use close prices
    """
    if df is None or len(df) < (2 * distance + 1):
        return []

    work = df.copy().reset_index(drop=True)
    if "date" not in work.columns:
        work["date"] = pd.to_datetime(work.index)

    if use_wick:
        highs = work["high"].values
        lows = work["low"].values
    else:
        highs = work["close"].values
        lows = work["close"].values

    high_idx = argrelextrema(highs, np.greater_equal, order=distance)[0]
    low_idx = argrelextrema(lows, np.less_equal, order=distance)[0]

    swings: List[Swing] = []
    for i in high_idx:
        swings.append(Swing(
            idx=int(i),
            date=pd.to_datetime(work["date"].iloc[i]),
            price=float(highs[i]),
            kind="high",
            volume=float(work["volume"].iloc[i]) if "volume" in work.columns else 0.0,
        ))
    for i in low_idx:
        swings.append(Swing(
            idx=int(i),
            date=pd.to_datetime(work["date"].iloc[i]),
            price=float(lows[i]),
            kind="low",
            volume=float(work["volume"].iloc[i]) if "volume" in work.columns else 0.0,
        ))

    # Alternating filter: collapse consecutive same-kind swings to keep only the extreme.
    swings.sort(key=lambda s: s.idx)
    alt: List[Swing] = []
    for s in swings:
        if alt and alt[-1].kind == s.kind:
            # keep the more extreme
            if s.kind == "high" and s.price > alt[-1].price:
                alt[-1] = s
            elif s.kind == "low" and s.price < alt[-1].price:
                alt[-1] = s
        else:
            alt.append(s)
    return alt


def recent_swings(swings: List[Swing], n: int = 6, kind: str | None = None
                  ) -> List[Swing]:
    """Last n swings, optionally filtered by kind."""
    pool = [s for s in swings if (kind is None or s.kind == kind)]
    return pool[-n:]


def find_swings_for_pattern(df: pd.DataFrame, lookback_bars: int,
                            distance: int = 5) -> List[Swing]:
    """Convenience: find swings within the last `lookback_bars` of df."""
    if df is None or len(df) == 0:
        return []
    tail = df.tail(lookback_bars).reset_index(drop=True)
    return find_swings(tail, distance=distance)
