"""Book's exact monthly 10MA crossover rule, implemented as a backtest.

Source: 캔들차트 하나로 끝내는 추세추종 투자 (성승현), p318-319.

Rule (verbatim from the book):
  - Entry: month-end close crosses ABOVE the 10-month MA.
  - Exit:  month-end close crosses BELOW the 10-month MA.
  - The book claims this rule on Samsung 2021-2026 yields ~4 entries
    with 3 wins / 1 small loss, asymmetric P&L (small losses, big wins).

This module is the cleanest way to test the book's claim: instead of
asking "does our 17-detector pipeline reproduce the book's call?"
(Kakao case) we apply the book's stated rule directly and check the
output against the book's numerical claims.

PIT-safe by construction: at each month-end we use only data up to
and including that month.

Usage:
    from app.backtest.book_cases.monthly_10ma_strategy import (
        load_monthly_bars, backtest_10ma,
    )
    bars = load_monthly_bars(fixture)
    trades = backtest_10ma(bars, start=date(2021,1,1), end=date(2026,1,31))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

log = logging.getLogger("backtest.book_cases.monthly_10ma")

_MA_WINDOW = 10


@dataclass
class Trade:
    entry_date: date
    entry_price: float
    exit_date: Optional[date]   # None if still open at end of window
    exit_price: Optional[float]
    return_pct: Optional[float]  # None if open

    def is_win(self) -> Optional[bool]:
        if self.return_pct is None:
            return None
        return self.return_pct > 0


def load_monthly_bars(fixture: Dict[str, Any]) -> pd.DataFrame:
    """Extract M bars from a fixture into a date-sorted df."""
    monthly = [b for b in fixture["bars"] if b["granularity"] == "M"]
    if not monthly:
        raise RuntimeError(f"fixture has no M bars: {fixture.get('ticker')}")
    df = pd.DataFrame(monthly)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "adj_close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def backtest_10ma(
    monthly_df: pd.DataFrame,
    start: Optional[date] = None,
    end: Optional[date] = None,
    ma_window: int = _MA_WINDOW,
) -> List[Trade]:
    """Apply the book's monthly 10MA crossover rule to monthly bars.

    `start` / `end` define the OBSERVATION window: every trade whose
    [entry_date, exit_date] interval overlaps the window is returned.
    Critically this INCLUDES a position entered just before `start`
    that exits within — which matches how a reader of the book's chart
    would count (the visible chart starts at `start` but the position
    was already running).

    The MA itself is computed on the full df so warmup before `start`
    is automatic. A trade still open at the last bar has exit_date /
    exit_price / return_pct set to None.
    """
    df = monthly_df.copy()
    df["ma10"] = df["close"].rolling(ma_window).mean()
    df = df.dropna(subset=["ma10"]).reset_index(drop=True)
    if df.empty:
        return []

    trades: List[Trade] = []
    holding = False
    entry_d: Optional[date] = None
    entry_p: Optional[float] = None

    for i in range(1, len(df)):
        bar_dt = df.iloc[i]["date"].date()
        close = float(df.iloc[i]["close"])
        ma_now = float(df.iloc[i]["ma10"])
        prev_close = float(df.iloc[i - 1]["close"])
        prev_ma = float(df.iloc[i - 1]["ma10"])

        crossed_up = prev_close <= prev_ma and close > ma_now
        crossed_dn = prev_close >= prev_ma and close < ma_now

        if not holding and crossed_up:
            holding = True
            entry_d, entry_p = bar_dt, close
        elif holding and crossed_dn:
            ret = (close / entry_p - 1.0) * 100.0
            trades.append(Trade(entry_d, entry_p, bar_dt, close, ret))
            holding = False
            entry_d, entry_p = None, None

    if holding and entry_d is not None and entry_p is not None:
        trades.append(Trade(entry_d, entry_p, None, None, None))

    if start is None and end is None:
        return trades

    def _overlaps(t: Trade) -> bool:
        t_start = t.entry_date
        t_end = t.exit_date if t.exit_date is not None else (
            end if end is not None else t_start
        )
        if start is not None and t_end < start:
            return False
        if end is not None and t_start > end:
            return False
        return True

    return [t for t in trades if _overlaps(t)]


def summarize(trades: List[Trade]) -> Dict[str, Any]:
    """Stats: n closed, wins, win rate, avg/best/worst, asymmetry ratio.

    Asymmetry ratio = avg_win / |avg_loss|. Book's claim is that this
    is > 1 (and the bigger the better). Open trades excluded from stats.
    """
    closed = [t for t in trades if t.return_pct is not None]
    if not closed:
        return {
            "n_total": len(trades),
            "n_closed": 0,
            "n_open": len(trades),
        }
    rets = [t.return_pct for t in closed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    asym = (avg_win / abs(avg_loss)) if (wins and losses) else None
    return {
        "n_total": len(trades),
        "n_closed": len(closed),
        "n_open": len(trades) - len(closed),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": len(wins) / len(closed),
        "avg_return_pct": sum(rets) / len(rets),
        "best_pct": max(rets),
        "worst_pct": min(rets),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "asymmetry": asym,   # avg_win / |avg_loss|
    }
