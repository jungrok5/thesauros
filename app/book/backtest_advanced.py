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
from app.book.trend import add_moving_averages, resample_to_period


UNIT_SIZE = 0.25            # 4등분: 한 unit = 25%
MAX_UNITS = 4               # 최대 4단까지 추매 (100%)


@dataclass
class TFParams:
    """Timeframe-aware tuning. 책 원문은 월봉 기준 룰 → 단기로 갈수록 더 보수.

    Reasoning:
      - 일봉: 노이즈 多 → EXIT 임계 매우 높게 (강신호만), PYRAMID 쿨다운 길게
      - 주봉: 책 권장. 균형
      - 월봉: 책 핵심. 가장 너그럽게 (신호 자체가 드물어서)
    """
    enter_min_conf: float = 0.60
    pyramid_min_conf: float = 0.70
    warn_min_conf: float = 0.55
    exit_min_conf: float = 0.80
    pyramid_cooldown_bars: int = 5
    require_240ma_above: bool = True       # 240MA 아래에선 ENTER 금지
    warn_require_red_candle: bool = True   # WARN 확정 시 음봉 필요
    warn_require_volume_up: bool = True    # WARN 확정 시 거래량 증가 필요
    warn_require_ma10_near: bool = True    # WARN 확정 시 10MA 근접 필요
    # ─── 책 강화 옵션 (V4) ───
    forbid_sideways_entry: bool = True      # 책 3장: 박스권 매매 금지
    forbid_bearish_alignment_entry: bool = True  # 책 4장: 역배열 매수 금지
    simple_book_exit: bool = False          # True = "월봉 10MA 하향" 만 EXIT (책 그대로)
    require_topdown_ok: bool = False        # macro.market_regime() 가 BULL/HOPE 이상 일 때만 ENTER
    trade_only_period_end: bool = False     # 책 3장: "말일/금요일 14시 1회"만 검사
    # 매매 검사 빈도 옵션 (모든 봉 대신):
    #   daily: weekday=4 (금요일) 만
    #   weekly: 모든 봉 (어차피 주봉 = 금요일 1회)
    #   monthly: 모든 봉 (월봉 = 말일)


def _book_strict_params(base: TFParams) -> TFParams:
    """V4: 책 그대로 모드 — 모든 책 강화 옵션 ON."""
    return TFParams(
        enter_min_conf=base.enter_min_conf,
        pyramid_min_conf=base.pyramid_min_conf,
        warn_min_conf=base.warn_min_conf,
        exit_min_conf=base.exit_min_conf,
        pyramid_cooldown_bars=base.pyramid_cooldown_bars,
        require_240ma_above=True,
        warn_require_red_candle=True,
        warn_require_volume_up=base.warn_require_volume_up,
        warn_require_ma10_near=base.warn_require_ma10_near,
        # 책 강화 옵션 ON
        forbid_sideways_entry=True,
        forbid_bearish_alignment_entry=True,
        simple_book_exit=True,        # 월봉 10MA 만 EXIT (책 그대로)
        require_topdown_ok=False,     # 백테스트 시 macro state 는 현재 시점만 — 비활성 (look-ahead)
        trade_only_period_end=True,   # 일봉이면 금요일만
    )


PARAMS_BY_TF: Dict[str, TFParams] = {
    "daily": TFParams(
        enter_min_conf=0.70,
        pyramid_min_conf=0.80,
        warn_min_conf=0.60,
        exit_min_conf=0.88,
        pyramid_cooldown_bars=20,
        require_240ma_above=True,
        warn_require_red_candle=True,
        warn_require_volume_up=True,
        warn_require_ma10_near=True,
    ),
    "weekly": TFParams(
        enter_min_conf=0.65,
        pyramid_min_conf=0.72,
        warn_min_conf=0.55,
        exit_min_conf=0.80,
        pyramid_cooldown_bars=4,
        require_240ma_above=True,
        warn_require_red_candle=True,
        warn_require_volume_up=False,
        warn_require_ma10_near=True,
    ),
    "monthly": TFParams(
        enter_min_conf=0.55,
        pyramid_min_conf=0.65,
        warn_min_conf=0.50,
        exit_min_conf=0.70,
        pyramid_cooldown_bars=2,
        require_240ma_above=False,    # 월봉 240 = 20년 데이터 필요해서 비활성
        warn_require_red_candle=True,
        warn_require_volume_up=False,
        warn_require_ma10_near=False,
    ),
}


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
def _confirm_warn(df_aug: pd.DataFrame, i: int, params: TFParams) -> bool:
    """다음 봉에서 WARN 신호가 진짜인지 확인.

    조건 (params 에 따라 활성):
      - 음봉 (close < open)
      - 직전 봉 종가 대비 하락
      - 거래량 증가 (직전 5봉 평균 이상)
      - 10MA 근접 (종가가 ma_10 ±3% 이내, 즉 깰 위험권)
    """
    if i < 1 or i >= len(df_aug):
        return False
    row = df_aug.iloc[i]
    prev = df_aug.iloc[i - 1]
    close = float(row["close"])
    open_ = float(row["open"])
    prev_close = float(prev["close"])

    if close >= prev_close:
        return False  # 상승이면 WARN 무효

    if params.warn_require_red_candle and close >= open_:
        return False

    if params.warn_require_volume_up and "volume" in df_aug.columns:
        v_now = float(row["volume"]) if pd.notna(row["volume"]) else 0
        prev5 = df_aug["volume"].iloc[max(0, i - 5): i]
        v_avg = float(prev5.mean()) if len(prev5) > 0 else 0
        if v_avg > 0 and v_now < v_avg * 1.0:
            return False

    if params.warn_require_ma10_near and "ma_10" in df_aug.columns:
        ma10 = df_aug["ma_10"].iloc[i]
        if pd.notna(ma10):
            ma10 = float(ma10)
            if close > ma10 * 1.03:
                return False  # 10MA 와 너무 멀면 아직 위험 없음

    return True


def _asof_higher_tf_uptrend(daily_dates: pd.Series,
                            higher_df: pd.DataFrame) -> pd.Series:
    """For each daily date, look up the most recent COMPLETED higher-TF bar
    and return whether close > ma_10 (uptrend) at that bar.

    Returns Series of bool aligned to daily_dates (True = uptrend, NaN→False).
    """
    if higher_df is None or higher_df.empty:
        return pd.Series([True] * len(daily_dates), index=daily_dates.index)
    h = higher_df.copy()
    h["date"] = pd.to_datetime(h["date"])
    h = h.sort_values("date").reset_index(drop=True)
    h = add_moving_averages(h, [10])
    h["uptrend"] = (h["close"] > h["ma_10"]).fillna(False)

    left = pd.DataFrame({"date": pd.to_datetime(daily_dates).values,
                          "_orig_idx": daily_dates.index})
    merged = pd.merge_asof(
        left.sort_values("date"),
        h[["date", "uptrend"]].sort_values("date"),
        on="date", direction="backward",
    )
    merged = merged.sort_values("_orig_idx")
    return merged["uptrend"].fillna(False).reset_index(drop=True)


def backtest_advanced(df: pd.DataFrame,
                       ticker: str,
                       timeframe: str = "daily",
                       warmup: int = 60,
                       params: Optional[TFParams] = None,
                       higher_tf_dfs: Optional[Dict[str, pd.DataFrame]] = None,
                       ) -> Dict:
    """Run the 4-tier state-machine backtest on a single OHLCV series.

    Args:
        df: OHLCV (date, open, high, low, close, volume). Already resampled
            to the desired timeframe (daily/weekly/monthly).
        ticker: ticker label (for output rows).
        timeframe: 'daily' / 'weekly' / 'monthly'. Used to pick tuning
            unless `params` is overridden.
        warmup: bars to skip before signals can fire.
        params: optional explicit TFParams (overrides timeframe default).

    Returns dict with:
        - trades: list of TradeResult
        - all_steps: flat step log
        - summary: aggregate stats vs B&H
    """
    if df is None or len(df) < warmup + 10:
        return {"trades": [], "all_steps": [], "summary": {}}

    p = params or PARAMS_BY_TF.get(timeframe, TFParams())

    df = df.copy().reset_index(drop=True)
    if "date" not in df.columns:
        df["date"] = pd.to_datetime(df.index)
    df["date"] = pd.to_datetime(df["date"])

    # 240MA gate + WARN 확정용 MA10 precompute
    df_aug = add_moving_averages(df, [10, 240])

    # Option A: 상위 TF 추세 게이트 (as-of join, look-ahead 차단)
    higher_uptrends: Dict[str, pd.Series] = {}
    if higher_tf_dfs:
        for name, hdf in higher_tf_dfs.items():
            higher_uptrends[name] = _asof_higher_tf_uptrend(df["date"], hdf)

    pos = Position(ticker=ticker)
    trades: List[TradeResult] = []
    all_steps: List[TradeStep] = []

    last_pyramid_bar: int = -10**6

    # 책 강화: 탑다운 게이트 (한 번 호출, 캐시)
    topdown_ok = True
    if p.require_topdown_ok:
        try:
            from app.macro.state import market_regime
            r = market_regime()
            topdown_ok = r.get("regime") in ("HOPE", "CONVICTION")
        except Exception:
            topdown_ok = True  # fail-open

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        bar_date = pd.to_datetime(bar["date"])
        bar_close = float(bar["close"])

        # 책 강화: 매매 빈도 (일봉이면 금요일만)
        if p.trade_only_period_end and timeframe == "daily":
            if bar_date.weekday() != 4:  # 0=월, 4=금
                continue

        try:
            ss = detect_signals_at(df, i)
        except Exception:
            continue

        # 책 강화: simple_book_exit 모드 — 10MA 하향 만 EXIT
        if p.simple_book_exit:
            exit_signals = [s for s in ss.signals
                             if s.kind == "EXIT" and "10MA" in s.source]
            has_exit = bool(exit_signals)
            best_exit = max(exit_signals, key=lambda s: s.confidence) if exit_signals else None
        else:
            has_exit = ss.has("EXIT", min_conf=p.exit_min_conf)
            best_exit = ss.best("EXIT") if has_exit else None
        has_warn = ss.has("WARN", min_conf=p.warn_min_conf)
        best_warn = ss.best("WARN") if has_warn else None
        has_pyramid = ss.has("PYRAMID", min_conf=p.pyramid_min_conf)
        best_pyramid = ss.best("PYRAMID") if has_pyramid else None
        has_enter = ss.has("ENTER", min_conf=p.enter_min_conf)
        best_enter = ss.best("ENTER") if has_enter else None

        # 책 게이트들 평가 (ENTER 차단용)
        gate_sideways_block = (
            p.forbid_sideways_entry and ss.trend_type == "sideways"
        )
        gate_bearish_align_block = (
            p.forbid_bearish_alignment_entry and ss.bearish_alignment
        )
        book_gates_ok = (
            not gate_sideways_block
            and not gate_bearish_align_block
            and topdown_ok
        )

        # 240MA gate: 가격이 240MA 아래면 ENTER 금지 (책: 죽은 차트 진입 차단)
        ma240_val = df_aug["ma_240"].iloc[i] if "ma_240" in df_aug.columns else None
        ma240_ok = (
            not p.require_240ma_above
            or (pd.notna(ma240_val) and bar_close >= float(ma240_val))
        )

        # Option A: 상위 TF 추세 게이트 (모두 상승 추세여야 ENTER 허용)
        higher_tf_ok = all(
            bool(s.iloc[i]) for s in higher_uptrends.values()
        ) if higher_uptrends else True

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

        # ----- 2. WARN 확정 (직전 bar 에 WARN 났고 이번 bar 가 조건 충족) -----
        if pos.is_open and pos.pending_warn:
            confirmed = _confirm_warn(df_aug, i, p)
            if confirmed and pos.units > UNIT_SIZE:
                step = pos.reduce_unit(
                    date=bar_date, price=bar_close, units=UNIT_SIZE,
                    action="SCALE_OUT",
                    source="WARN 확정 (음봉+거래량+10MA근접)",
                    detail=f"prev WARN: {pos.pending_warn_date}",
                )
                all_steps.append(step)
            pos.pending_warn = False
            pos.pending_warn_date = None

        # ----- 3. PYRAMID (보유 중 + 강한 상승 신호) -----
        if pos.is_open and has_pyramid and pos.units < 1.0 - 1e-6:
            if i - last_pyramid_bar >= p.pyramid_cooldown_bars:
                step = pos.add_unit(
                    date=bar_date, price=bar_close, units=UNIT_SIZE,
                    action="PYRAMID",
                    source=best_pyramid.source,
                    detail=best_pyramid.detail,
                )
                all_steps.append(step)
                last_pyramid_bar = i

        # ----- 4. ENTER (포지션 없음 + 진입 신호 + 게이트 모두 통과) -----
        if (not pos.is_open
                and has_enter
                and not has_warn
                and ma240_ok
                and higher_tf_ok
                and book_gates_ok):
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
# Option B: Triple Screen — daily 봉 단위로 매매, 상위 TF 동시 합의 필요
# ---------------------------------------------------------------------------
def backtest_triple_screen(daily_df: pd.DataFrame,
                            ticker: str,
                            warmup: int = 60,
                            params: Optional[TFParams] = None,
                            require_weekly_pattern: bool = False) -> Dict:
    """3-time-frame consensus backtest (Alexander Elder Triple Screen 변형).

    실행 단위 = 일봉. 매 일봉에서:
      1. 월봉의 마지막 완성된 봉 → 추세 양호?  (close > 10MA)
      2. 주봉의 마지막 완성된 봉 → 추세 양호?
      3. 일봉의 현재 봉 → ENTER 신호?
    셋 다 OK 일 때만 매수. EXIT 는 일봉 한 곳에서만 발동돼도 청산.
    """
    p = params or PARAMS_BY_TF.get("daily", TFParams())

    df = daily_df.copy().reset_index(drop=True)
    if "date" not in df.columns:
        df["date"] = pd.to_datetime(df.index)
    df["date"] = pd.to_datetime(df["date"])

    weekly = resample_to_period(daily_df, "W").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in weekly.columns:
        weekly = weekly.rename(columns={weekly.columns[0]: "date"})
    monthly = resample_to_period(daily_df, "M").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in monthly.columns:
        monthly = monthly.rename(columns={monthly.columns[0]: "date"})

    return backtest_advanced(
        df=df, ticker=ticker, timeframe="daily",
        warmup=warmup, params=p,
        higher_tf_dfs={"weekly": weekly, "monthly": monthly},
    )


# ---------------------------------------------------------------------------
# Multi-timeframe driver
# ---------------------------------------------------------------------------
def backtest_advanced_all_timeframes(daily_df: pd.DataFrame,
                                     ticker: str,
                                     use_higher_tf_gate: bool = False,
                                     book_strict: bool = False) -> Dict:
    """Run the same state machine on daily / weekly / monthly bars.

    Args:
        use_higher_tf_gate: Option A. If True, daily backtest is gated by
            weekly + monthly uptrend; weekly is gated by monthly uptrend.
    """
    out: Dict[str, Dict] = {}

    # Resample once (reused for gates)
    weekly = resample_to_period(daily_df, "W").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in weekly.columns:
        weekly = weekly.rename(columns={weekly.columns[0]: "date"})
    monthly = resample_to_period(daily_df, "M").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in monthly.columns:
        monthly = monthly.rename(columns={monthly.columns[0]: "date"})

    daily_gates = {"weekly": weekly, "monthly": monthly} if use_higher_tf_gate else None
    weekly_gates = {"monthly": monthly} if use_higher_tf_gate else None

    def _params(tf: str) -> TFParams:
        base = PARAMS_BY_TF.get(tf, TFParams())
        return _book_strict_params(base) if book_strict else base

    out["daily"] = backtest_advanced(
        daily_df.copy(), ticker, "daily", warmup=60,
        params=_params("daily"), higher_tf_dfs=daily_gates,
    )
    out["weekly"] = backtest_advanced(
        weekly, ticker, "weekly", warmup=30,
        params=_params("weekly"), higher_tf_dfs=weekly_gates,
    )
    out["monthly"] = backtest_advanced(
        monthly, ticker, "monthly", warmup=24,
        params=_params("monthly"),
    )
    return out
