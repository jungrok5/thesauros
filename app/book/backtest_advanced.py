"""Advanced book backtest — 4단 매수/매도 state machine.

책의 모든 패턴 + 신호를 하나의 엔진으로 통합:

  매수 (ENTER)   → 25% unit (1단계 진입)
  강한 상승      → 추매 +25% (PYRAMID, 최대 4단까지)
  팔자 고치는 패턴 → 추매 +25%
  하락 경고 (WARN) → 다음 봉에서 확정되면 25% 분할 매도
  무조건 청산 (EXIT) → 보유분 전량 청산

월봉 / 주봉 / 일봉 별로 동일 룰을 다른 timeframe 에 적용해서 비교.

Output:
  - 종목별 trade ledger
  - 진입/추매/분할매도/청산 step log
  - 시간프레임별 요약 통계 (CAGR, 승률, 최대낙폭, B&H 대비)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.book.signals import detect_signals_at, SignalSet
from app.book.trend import resample_to_period


UNIT_SIZE = 0.25            # 4등분: 한 unit = 25%
MAX_UNITS = 4               # 최대 4단까지 추매 (100%)
WARN_CONFIRM_BARS = 1       # WARN 다음 봉에서 EXIT/하락 확인 시 분할 매도

# 시그널 confidence 임계값 — 낮은 noise 시그널 무시
ENTER_MIN_CONF = 0.60
PYRAMID_MIN_CONF = 0.70
WARN_MIN_CONF = 0.50
EXIT_MIN_CONF = 0.70


# ---------------------------------------------------------------------------
# Trade ledger
# ---------------------------------------------------------------------------
@dataclass
class TradeStep:
    """One state transition: BUY / PYRAMID / SCALE_OUT / EXIT."""
    date: pd.Timestamp
    action: str                # "BUY" / "PYRAMID" / "SCALE_OUT" / "EXIT"
    price: float
    units_delta: float         # +0.25 / -0.25 / -1.0
    units_after: float         # cumulative after this step
    source: str                # 책 시그널 source
    detail: str = ""

    def to_dict(self) -> Dict:
        return {
            "date": str(self.date.date() if hasattr(self.date, "date") else self.date),
            "action": self.action,
            "price": round(float(self.price), 4),
            "units_delta": round(float(self.units_delta), 3),
            "units_after": round(float(self.units_after), 3),
            "source": self.source,
            "detail": self.detail,
        }


@dataclass
class Position:
    """In-flight position state."""
    ticker: str
    units: float = 0.0                    # 0..1 (1 = 100% 풀 포지션)
    avg_entry: float = 0.0                # weighted avg entry
    cost_basis: float = 0.0               # cumulative cost (units * price)
    open_date: Optional[pd.Timestamp] = None
    pending_warn: bool = False            # WARN 발동 후 다음 봉 대기
    pending_warn_date: Optional[pd.Timestamp] = None
    steps: List[TradeStep] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.units > 1e-6

    def add_unit(self, date, price: float, units: float,
                 action: str, source: str, detail: str = "") -> TradeStep:
        if units > 0:
            new_cost = self.cost_basis + units * price
            new_units = self.units + units
            self.avg_entry = new_cost / new_units if new_units > 0 else 0
            self.cost_basis = new_cost
            self.units = new_units
        if self.open_date is None:
            self.open_date = date
        step = TradeStep(date=date, action=action, price=price,
                         units_delta=+units, units_after=self.units,
                         source=source, detail=detail)
        self.steps.append(step)
        return step

    def reduce_unit(self, date, price: float, units: float,
                    action: str, source: str, detail: str = "") -> TradeStep:
        """Sell `units` (>0). Cost basis reduces proportionally."""
        units = min(units, self.units)
        if self.units > 0:
            cost_per_unit = self.cost_basis / self.units
            self.cost_basis -= cost_per_unit * units
        self.units -= units
        step = TradeStep(date=date, action=action, price=price,
                         units_delta=-units, units_after=self.units,
                         source=source, detail=detail)
        self.steps.append(step)
        return step


@dataclass
class TradeResult:
    """Closed (or end-of-series) trade summary."""
    ticker: str
    timeframe: str
    open_date: pd.Timestamp
    close_date: pd.Timestamp
    avg_entry: float
    avg_exit: float
    max_units: float
    return_pct: float
    bars_held: int
    steps: List[TradeStep]
    close_reason: str

    def to_dict(self) -> Dict:
        return {
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "open_date": str(self.open_date.date()),
            "close_date": str(self.close_date.date()),
            "avg_entry": round(self.avg_entry, 4),
            "avg_exit": round(self.avg_exit, 4),
            "max_units": round(self.max_units, 3),
            "return_pct": round(self.return_pct, 2),
            "bars_held": int(self.bars_held),
            "close_reason": self.close_reason,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# State-machine backtest on a single timeframe
# ---------------------------------------------------------------------------
def backtest_advanced(df: pd.DataFrame,
                       ticker: str,
                       timeframe: str = "daily",
                       warmup: int = 60) -> Dict:
    """Run the 4-tier state-machine backtest on a single OHLCV series.

    Args:
        df: OHLCV (date, open, high, low, close, volume). Already resampled
            to the desired timeframe (daily/weekly/monthly).
        ticker: ticker label (for output rows).
        timeframe: 'daily' / 'weekly' / 'monthly' (annotation only).
        warmup: bars to skip before signals can fire.

    Returns dict with:
        - trades: list of TradeResult
        - all_steps: flat step log
        - summary: aggregate stats vs B&H
    """
    if df is None or len(df) < warmup + 10:
        return {"trades": [], "all_steps": [], "summary": {}}

    df = df.copy().reset_index(drop=True)
    if "date" not in df.columns:
        df["date"] = pd.to_datetime(df.index)
    df["date"] = pd.to_datetime(df["date"])

    pos = Position(ticker=ticker)
    trades: List[TradeResult] = []
    all_steps: List[TradeStep] = []

    last_pyramid_bar: int = -10  # debounce: don't add two units in two adjacent bars

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        bar_date = pd.to_datetime(bar["date"])
        bar_close = float(bar["close"])

        try:
            ss = detect_signals_at(df, i)
        except Exception:
            continue

        has_exit = ss.has("EXIT", min_conf=EXIT_MIN_CONF)
        best_exit = ss.best("EXIT") if has_exit else None
        has_warn = ss.has("WARN", min_conf=WARN_MIN_CONF)
        best_warn = ss.best("WARN") if has_warn else None
        has_pyramid = ss.has("PYRAMID", min_conf=PYRAMID_MIN_CONF)
        best_pyramid = ss.best("PYRAMID") if has_pyramid else None
        has_enter = ss.has("ENTER", min_conf=ENTER_MIN_CONF)
        best_enter = ss.best("ENTER") if has_enter else None

        # ----- 1. EXIT (보유 중이면 즉시 청산) -----
        if pos.is_open and has_exit:
            units_before = pos.units
            avg_entry = pos.avg_entry
            step = pos.reduce_unit(
                date=bar_date, price=bar_close, units=pos.units,
                action="EXIT",
                source=best_exit.source,
                detail=best_exit.detail,
            )
            all_steps.append(step)
            ret = (bar_close - avg_entry) / avg_entry * 100 if avg_entry > 0 else 0
            trades.append(TradeResult(
                ticker=ticker, timeframe=timeframe,
                open_date=pos.open_date, close_date=bar_date,
                avg_entry=avg_entry, avg_exit=bar_close,
                max_units=max(s.units_after for s in pos.steps),
                return_pct=ret,
                bars_held=int((bar_date - pos.open_date).days),
                steps=list(pos.steps),
                close_reason=f"EXIT: {best_exit.source}",
            ))
            pos = Position(ticker=ticker)
            continue

        # ----- 2. WARN 확정 (직전 bar 에 WARN 났고 이번 bar 가 하락 종가면 부분 매도) -----
        if pos.is_open and pos.pending_warn:
            prev_close = float(df["close"].iloc[i - 1])
            confirmed = bar_close < prev_close  # 다음 봉 하락 = 확정
            if confirmed and pos.units > UNIT_SIZE:
                step = pos.reduce_unit(
                    date=bar_date, price=bar_close, units=UNIT_SIZE,
                    action="SCALE_OUT",
                    source="WARN 확정 (전봉 경고 후 하락)",
                    detail=f"prev_close {prev_close:.2f} → {bar_close:.2f}",
                )
                all_steps.append(step)
            pos.pending_warn = False
            pos.pending_warn_date = None

        # ----- 3. PYRAMID (보유 중 + 강한 상승 신호) -----
        if pos.is_open and has_pyramid and pos.units < 1.0 - 1e-6:
            if i - last_pyramid_bar >= 2:  # 연속 추매 방지
                step = pos.add_unit(
                    date=bar_date, price=bar_close, units=UNIT_SIZE,
                    action="PYRAMID",
                    source=best_pyramid.source,
                    detail=best_pyramid.detail,
                )
                all_steps.append(step)
                last_pyramid_bar = i

        # ----- 4. ENTER (포지션 없음 + 진입 신호) -----
        if not pos.is_open and has_enter and not has_warn:
            step = pos.add_unit(
                date=bar_date, price=bar_close, units=UNIT_SIZE,
                action="BUY",
                source=best_enter.source,
                detail=best_enter.detail,
            )
            all_steps.append(step)
            last_pyramid_bar = i

        # ----- 5. WARN 신규 마크 (다음 봉에서 확정 검사) -----
        if pos.is_open and has_warn and not pos.pending_warn:
            pos.pending_warn = True
            pos.pending_warn_date = bar_date

    # End-of-series: close any open position at last bar
    if pos.is_open:
        bar = df.iloc[-1]
        bar_date = pd.to_datetime(bar["date"])
        bar_close = float(bar["close"])
        avg_entry = pos.avg_entry
        step = pos.reduce_unit(
            date=bar_date, price=bar_close, units=pos.units,
            action="EXIT", source="EOS (시리즈 종료)",
            detail="시계열 마지막 봉에서 강제 청산",
        )
        all_steps.append(step)
        ret = (bar_close - avg_entry) / avg_entry * 100 if avg_entry > 0 else 0
        trades.append(TradeResult(
            ticker=ticker, timeframe=timeframe,
            open_date=pos.open_date, close_date=bar_date,
            avg_entry=avg_entry, avg_exit=bar_close,
            max_units=max(s.units_after for s in pos.steps),
            return_pct=ret,
            bars_held=int((bar_date - pos.open_date).days),
            steps=list(pos.steps),
            close_reason="EOS",
        ))

    summary = _summarize(trades, df, timeframe)
    return {
        "trades": trades,
        "all_steps": all_steps,
        "summary": summary,
    }


def _summarize(trades: List[TradeResult], df: pd.DataFrame,
               timeframe: str) -> Dict:
    if not trades:
        first_px = float(df["close"].iloc[0])
        last_px = float(df["close"].iloc[-1])
        years = max((df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25, 1e-6)
        bh_ret = (last_px / first_px - 1) * 100
        bh_cagr = ((last_px / first_px) ** (1 / years) - 1) * 100
        return {
            "timeframe": timeframe, "n_trades": 0,
            "buy_and_hold_pct": round(bh_ret, 2),
            "buy_and_hold_cagr": round(bh_cagr, 2),
        }

    rets = np.array([t.return_pct for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    total_compound = np.prod(1 + rets / 100) - 1
    years = max((df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25, 1e-6)
    cagr = ((1 + total_compound) ** (1 / years) - 1) * 100

    # Buy & hold same window
    first_px = float(df["close"].iloc[0])
    last_px = float(df["close"].iloc[-1])
    bh_ret = (last_px / first_px - 1) * 100
    bh_cagr = ((last_px / first_px) ** (1 / years) - 1) * 100

    n_pyramid = sum(
        sum(1 for s in t.steps if s.action == "PYRAMID") for t in trades
    )
    n_scale_out = sum(
        sum(1 for s in t.steps if s.action == "SCALE_OUT") for t in trades
    )

    return {
        "timeframe": timeframe,
        "n_trades": len(trades),
        "n_pyramid_adds": int(n_pyramid),
        "n_scale_outs": int(n_scale_out),
        "win_rate_pct": round(float(len(wins)) / len(rets) * 100, 2),
        "avg_return_pct": round(float(rets.mean()), 2),
        "avg_winner_pct": round(float(wins.mean()) if len(wins) else 0, 2),
        "avg_loser_pct": round(float(losses.mean()) if len(losses) else 0, 2),
        "best_pct": round(float(rets.max()), 2),
        "worst_pct": round(float(rets.min()), 2),
        "total_compound_pct": round(float(total_compound * 100), 2),
        "cagr_pct": round(float(cagr), 2),
        "buy_and_hold_pct": round(bh_ret, 2),
        "buy_and_hold_cagr": round(bh_cagr, 2),
        "alpha_cagr_pct": round(float(cagr - bh_cagr), 2),
    }


# ---------------------------------------------------------------------------
# Multi-timeframe driver
# ---------------------------------------------------------------------------
def backtest_advanced_all_timeframes(daily_df: pd.DataFrame,
                                     ticker: str) -> Dict:
    """Run the same state machine on daily / weekly / monthly bars."""
    out: Dict[str, Dict] = {}
    # Daily
    out["daily"] = backtest_advanced(daily_df.copy(), ticker, "daily", warmup=60)

    # Weekly
    weekly = resample_to_period(daily_df, "W").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in weekly.columns:
        weekly = weekly.rename(columns={weekly.columns[0]: "date"})
    out["weekly"] = backtest_advanced(weekly, ticker, "weekly", warmup=30)

    # Monthly
    monthly = resample_to_period(daily_df, "M").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in monthly.columns:
        monthly = monthly.rename(columns={monthly.columns[0]: "date"})
    out["monthly"] = backtest_advanced(monthly, ticker, "monthly", warmup=24)

    return out
