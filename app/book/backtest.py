"""Backtest the book's rules over historical data.

Strategy = book's core rules:
  Entry signals:
    A. 월봉 10MA 상향 돌파 (단순 추세 추종, 책 권장 빈도 = 월 1회 점검)
    B. 240MA 돌파매매 (책의 옥석 중 옥석)
    C. 짝궁둥이 쌍바닥 / 역H&S / Cup-Handle 패턴 완성
  Exit signals (whichever first):
    1. 월봉 10MA 하향 돌파 → 100% 청산 (책: 무조건 청산)
    2. 주봉 10MA 하향 돌파 → 50% 부분 청산 (보수적)
    3. 진입 가격 -7% 도달 (whipsaw 보호)

This module powers two CLI flows:
  - `backtest TICKER`              — backtest one stock end-to-end
  - `book-cases`                   — verify book's headline examples
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.book.trend import resample_to_period


@dataclass
class Trade:
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    strategy: str = ""           # "monthly_10ma" / "weekly_10ma" / "240ma_break"
    return_pct: Optional[float] = None
    bars_held: int = 0
    exit_reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "entry_date": str(self.entry_date.date()),
            "entry_price": round(self.entry_price, 4),
            "exit_date": (str(self.exit_date.date()) if self.exit_date else None),
            "exit_price": (round(self.exit_price, 4) if self.exit_price else None),
            "strategy": self.strategy,
            "return_pct": (round(self.return_pct, 2) if self.return_pct is not None else None),
            "bars_held": int(self.bars_held),
            "exit_reason": self.exit_reason,
        }


def _ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=max(1, period // 3)).mean()


def backtest_monthly_10ma(df: pd.DataFrame, stop_pct: float = -0.07) -> List[Trade]:
    """가장 단순한 책 룰: 월봉 10MA 상향 돌파 진입, 하향 돌파 청산.

    Daily df → monthly OHLCV → monthly 10MA cross signals.
    Trade execution happens on the monthly bar's close (책: 말일 14시 확인).
    """
    if df is None or len(df) < 30 * 22:   # ~30 months
        return []
    monthly = resample_to_period(df, "M")
    if len(monthly) < 12:
        return []
    monthly["ma_10"] = _ma(monthly["close"], 10)

    trades: List[Trade] = []
    pos = False
    entry = None

    for i in range(11, len(monthly)):
        row = monthly.iloc[i]
        prev = monthly.iloc[i - 1]
        if np.isnan(row["ma_10"]) or np.isnan(prev["ma_10"]):
            continue
        crossed_up = prev["close"] <= prev["ma_10"] and row["close"] > row["ma_10"]
        crossed_dn = prev["close"] >= prev["ma_10"] and row["close"] < row["ma_10"]

        if not pos and crossed_up:
            entry = Trade(
                entry_date=monthly.index[i],
                entry_price=float(row["close"]),
                strategy="monthly_10ma",
            )
            pos = True
        elif pos and entry is not None:
            cur_price = float(row["close"])
            ret = (cur_price - entry.entry_price) / entry.entry_price
            if crossed_dn:
                entry.exit_date = monthly.index[i]
                entry.exit_price = cur_price
                entry.return_pct = ret * 100
                entry.bars_held = i - monthly.index.get_loc(entry.entry_date)
                entry.exit_reason = "월봉 10MA 하향 돌파"
                trades.append(entry)
                entry = None
                pos = False
            elif ret <= stop_pct:
                entry.exit_date = monthly.index[i]
                entry.exit_price = cur_price
                entry.return_pct = ret * 100
                entry.bars_held = i - monthly.index.get_loc(entry.entry_date)
                entry.exit_reason = f"손절선 {stop_pct*100:.1f}%"
                trades.append(entry)
                entry = None
                pos = False

    # Open position at end
    if pos and entry is not None:
        last = monthly.iloc[-1]
        cur_price = float(last["close"])
        entry.exit_date = monthly.index[-1]
        entry.exit_price = cur_price
        entry.return_pct = (cur_price - entry.entry_price) / entry.entry_price * 100
        entry.bars_held = len(monthly) - 1 - monthly.index.get_loc(entry.entry_date)
        entry.exit_reason = "open (시뮬레이션 종료)"
        trades.append(entry)

    return trades


def backtest_weekly_10ma(df: pd.DataFrame, stop_pct: float = -0.05) -> List[Trade]:
    """주봉 10MA crossover variant (보다 활동적, 책: 금요일 14시 확인)."""
    if df is None or len(df) < 50 * 5:
        return []
    weekly = resample_to_period(df, "W")
    if len(weekly) < 30:
        return []
    weekly["ma_10"] = _ma(weekly["close"], 10)

    trades: List[Trade] = []
    pos = False
    entry: Optional[Trade] = None

    for i in range(11, len(weekly)):
        row = weekly.iloc[i]
        prev = weekly.iloc[i - 1]
        if np.isnan(row["ma_10"]) or np.isnan(prev["ma_10"]):
            continue
        crossed_up = prev["close"] <= prev["ma_10"] and row["close"] > row["ma_10"]
        crossed_dn = prev["close"] >= prev["ma_10"] and row["close"] < row["ma_10"]

        if not pos and crossed_up:
            entry = Trade(entry_date=weekly.index[i], entry_price=float(row["close"]),
                          strategy="weekly_10ma")
            pos = True
        elif pos and entry is not None:
            cur_price = float(row["close"])
            ret = (cur_price - entry.entry_price) / entry.entry_price
            if crossed_dn or ret <= stop_pct:
                entry.exit_date = weekly.index[i]
                entry.exit_price = cur_price
                entry.return_pct = ret * 100
                entry.bars_held = i - weekly.index.get_loc(entry.entry_date)
                entry.exit_reason = "주봉 10MA 이탈" if crossed_dn else f"손절 {stop_pct*100:.1f}%"
                trades.append(entry)
                entry = None
                pos = False

    if pos and entry is not None:
        last = weekly.iloc[-1]
        cur_price = float(last["close"])
        entry.exit_date = weekly.index[-1]
        entry.exit_price = cur_price
        entry.return_pct = (cur_price - entry.entry_price) / entry.entry_price * 100
        entry.bars_held = len(weekly) - 1 - weekly.index.get_loc(entry.entry_date)
        entry.exit_reason = "open"
        trades.append(entry)

    return trades


@dataclass
class BacktestReport:
    ticker: str
    strategy: str
    period: str
    n_trades: int
    win_rate: float
    avg_gain_winners: float
    avg_loss_losers: float
    total_return_pct: float
    avg_return_pct: float
    max_drawdown_trade: float
    bars_in_market_pct: float
    buy_and_hold_return_pct: float
    trades: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = self.__dict__.copy()
        d["trades"] = self.trades
        return d


def summarize(ticker: str, strategy: str, df: pd.DataFrame,
              trades: List[Trade]) -> BacktestReport:
    if df is None or len(df) == 0:
        return BacktestReport(ticker=ticker, strategy=strategy, period="-",
                              n_trades=0, win_rate=0.0,
                              avg_gain_winners=0.0, avg_loss_losers=0.0,
                              total_return_pct=0.0, avg_return_pct=0.0,
                              max_drawdown_trade=0.0, bars_in_market_pct=0.0,
                              buy_and_hold_return_pct=0.0, trades=[])

    closed = [t for t in trades if t.return_pct is not None]
    winners = [t for t in closed if t.return_pct > 0]
    losers = [t for t in closed if t.return_pct <= 0]
    win_rate = len(winners) / len(closed) if closed else 0.0
    avg_gain = float(np.mean([t.return_pct for t in winners])) if winners else 0.0
    avg_loss = float(np.mean([t.return_pct for t in losers])) if losers else 0.0
    avg_return = float(np.mean([t.return_pct for t in closed])) if closed else 0.0

    # Compound returns (per-trade compounded)
    total = 1.0
    max_dd = 0.0
    for t in closed:
        total *= 1 + t.return_pct / 100
        if t.return_pct < max_dd:
            max_dd = t.return_pct
    total_ret_pct = (total - 1) * 100

    # Buy and hold
    bh = (float(df["close"].iloc[-1]) - float(df["close"].iloc[0])) / float(df["close"].iloc[0]) * 100

    # Time in market
    bars_in = sum(t.bars_held for t in closed if t.bars_held)
    # Convert to daily bars approximation
    if strategy == "monthly_10ma":
        bars_in *= 21
    elif strategy == "weekly_10ma":
        bars_in *= 5
    total_bars = len(df)
    in_pct = bars_in / total_bars * 100 if total_bars else 0

    return BacktestReport(
        ticker=ticker,
        strategy=strategy,
        period=f"{df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}"
        if "date" in df.columns else "-",
        n_trades=len(closed),
        win_rate=round(win_rate * 100, 1),
        avg_gain_winners=round(avg_gain, 2),
        avg_loss_losers=round(avg_loss, 2),
        total_return_pct=round(total_ret_pct, 2),
        avg_return_pct=round(avg_return, 2),
        max_drawdown_trade=round(max_dd, 2),
        bars_in_market_pct=round(in_pct, 1),
        buy_and_hold_return_pct=round(bh, 2),
        trades=[t.to_dict() for t in closed],
    )


def backtest_ticker(ticker: str, df: pd.DataFrame,
                    strategy: str = "monthly_10ma") -> BacktestReport:
    """Backtest one ticker with the requested book strategy."""
    if strategy == "monthly_10ma":
        trades = backtest_monthly_10ma(df)
    elif strategy == "weekly_10ma":
        trades = backtest_weekly_10ma(df)
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    return summarize(ticker, strategy, df, trades)


# ---------------------------------------------------------------------------
# Book cases (validation of book's headline claims)
# ---------------------------------------------------------------------------
BOOK_CASES = [
    # (ticker, claim_pct, claim_period_kr, claim_strategy_kr)
    ("AAPL", None, "2020-2026 추세 추종", "월봉 10MA"),
    ("MSFT", None, "장기 추세", "월봉 10MA"),
    ("005930.KS", None, "삼성전자 5년 (책 p319)", "월봉 10MA"),
    ("035720.KS", 390, "카카오 2019-2021 (책 p264-265)", "월봉 10MA"),
    ("319660.KS", 388, "피에스케이홀딩스 (책 p350-353)", "240MA 돌파"),
    ("328280.KS", 450, "SAMG엔터 (책 p276-279)", "삼중바닥"),
]
