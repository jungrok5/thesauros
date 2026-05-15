"""Portfolio-level book backtest — ML 백테스트와 공평 비교용.

ML walkforward 와 같은 형식:
  - universe: 사용자가 넘김 (e.g. S&P500 501 종목)
  - 기간: start_date ~ end_date
  - 매주 금요일 종가 기준 결정 (책: "금요일 14시 1회 점검")
  - 등가중 max_holdings (default 30)
  - 벤치마크: 등가중 buy-and-hold of universe (ML 과 동일)
  - 메트릭: CAGR, 알파, Sharpe, MDD, vol, total_return, win_rate_daily

각 종목 단위 state machine:
  ENTER → 25% unit (portfolio 의 1/max_holdings × 0.25)
  PYRAMID → +25% (cap 4 units = full slot)
  WARN → 다음 봉 확정 → -25%
  EXIT → 전량
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.book.backtest_advanced import (
    TFParams, PARAMS_BY_TF, _book_strict_params, Position,
)
from app.book.signals import detect_signals_at, SignalSet
from app.book.trend import resample_to_period
from app.cache.signal_cache import SignalCache


@dataclass
class PortfolioParams:
    start: pd.Timestamp = pd.Timestamp("2020-01-02")
    end: pd.Timestamp = pd.Timestamp("2024-12-31")
    max_holdings: int = 30           # ML V2/V3 top_k 와 매칭
    decision_freq: str = "weekly"    # weekly = 금요일 / daily = 매일 / monthly = 말일
    cost_bps: float = 10.0           # 단방향 거래비용
    book_strict: bool = True         # V4 책 strict 모드


@dataclass
class PortfolioMetrics:
    cagr: float
    bench_cagr: float
    alpha: float
    vol_annual: float
    sharpe: float
    info_ratio: float
    max_drawdown: float
    win_rate_daily: float
    total_return: float
    bench_total_return: float
    n_days: int


def _load_universe_prices(tickers: List[str],
                           start: pd.Timestamp,
                           end: pd.Timestamp) -> Dict[str, pd.DataFrame]:
    """Batch-load daily OHLCV for all tickers in one DuckDB query, then split."""
    from app.data.pit_db import cursor
    warmup_start = start - pd.Timedelta(days=400)
    with cursor() as con:
        all_df = con.execute(
            "SELECT ticker, date, open, high, low, close, volume "
            "FROM prices WHERE ticker = ANY(?) "
            "AND date >= ? AND date <= ? "
            "ORDER BY ticker, date",
            [tickers, warmup_start.date(), end.date()],
        ).df()
    if all_df.empty:
        return {}
    all_df["date"] = pd.to_datetime(all_df["date"])
    out: Dict[str, pd.DataFrame] = {}
    for tk, grp in all_df.groupby("ticker", sort=False):
        if len(grp) < 250:
            continue
        df = grp.drop(columns=["ticker"]).reset_index(drop=True)
        out[tk] = df
    return out


def _load_daily_close_panel(tickers: List[str],
                              start: pd.Timestamp,
                              end: pd.Timestamp) -> pd.DataFrame:
    """Batch-load only daily close prices (for portfolio mark-to-market).

    Returns a wide DataFrame: index=date, columns=ticker, values=close.
    Much cheaper than full OHLCV when cache is warm.
    """
    from app.data.pit_db import cursor
    with cursor() as con:
        long_df = con.execute(
            "SELECT ticker, date, close FROM prices "
            "WHERE ticker = ANY(?) AND date >= ? AND date <= ? "
            "ORDER BY date, ticker",
            [tickers, start.date(), end.date()],
        ).df()
    if long_df.empty:
        return pd.DataFrame()
    long_df["date"] = pd.to_datetime(long_df["date"])
    wide = long_df.pivot(index="date", columns="ticker", values="close")
    return wide


def _resample_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    w = resample_to_period(daily_df, "W").reset_index().rename(
        columns={"index": "date"}
    )
    if "date" not in w.columns:
        w = w.rename(columns={w.columns[0]: "date"})
    return w


def _decide_from_ss(ss: SignalSet, pos: Position, p: TFParams,
                     bar_close: float, prev_close: float,
                     ma240_val: Optional[float]) -> Tuple[str, Optional[str]]:
    """Apply book V4 priority logic to a pre-computed SignalSet."""
    has_exit_full = ss.has("EXIT", min_conf=p.exit_min_conf)
    if p.simple_book_exit:
        exit_signals = [s for s in ss.signals
                         if s.kind == "EXIT" and "10MA" in s.source]
        has_exit = bool(exit_signals)
        best_exit_src = max(exit_signals, key=lambda s: s.confidence).source if exit_signals else None
    else:
        has_exit = has_exit_full
        best_exit_src = ss.best("EXIT").source if has_exit else None

    has_warn = ss.has("WARN", min_conf=p.warn_min_conf)
    has_pyramid = ss.has("PYRAMID", min_conf=p.pyramid_min_conf)
    best_pyramid_src = ss.best("PYRAMID").source if has_pyramid else None
    has_enter = ss.has("ENTER", min_conf=p.enter_min_conf)
    best_enter_src = ss.best("ENTER").source if has_enter else None

    ma240_ok = (
        not p.require_240ma_above
        or (ma240_val is not None and bar_close >= ma240_val)
    )
    sideways_block = (p.forbid_sideways_entry and ss.trend_type == "sideways")
    bearish_block = (p.forbid_bearish_alignment_entry and ss.bearish_alignment)
    book_gates_ok = (not sideways_block) and (not bearish_block)

    if pos.is_open and has_exit:
        return ("EXIT", best_exit_src)

    if pos.is_open and pos.pending_warn:
        if bar_close < prev_close and pos.units > 0.25:
            return ("SCALE_OUT", "WARN 확정")

    if pos.is_open and has_pyramid and pos.units < 1.0 - 1e-6:
        return ("PYRAMID", best_pyramid_src)

    if (not pos.is_open) and has_enter and (not has_warn) and ma240_ok and book_gates_ok:
        return ("ENTER", best_enter_src)

    if pos.is_open and has_warn and not pos.pending_warn:
        return ("WARN_MARK", None)

    return ("HOLD", None)


def _signal_decision(weekly_df: pd.DataFrame, week_idx: int,
                      pos: Position, p: TFParams,
                      df_aug: pd.DataFrame) -> Tuple[str, Optional[str]]:
    """Legacy non-cached path. Computes signals on the fly."""
    if week_idx < 60 or week_idx >= len(weekly_df):
        return ("HOLD", None)
    try:
        ss = detect_signals_at(weekly_df, week_idx)
    except Exception:
        return ("HOLD", None)

    has_exit_full = ss.has("EXIT", min_conf=p.exit_min_conf)
    if p.simple_book_exit:
        exit_signals = [s for s in ss.signals
                         if s.kind == "EXIT" and "10MA" in s.source]
        has_exit = bool(exit_signals)
        best_exit_src = max(exit_signals, key=lambda s: s.confidence).source if exit_signals else None
    else:
        has_exit = has_exit_full
        best_exit_src = ss.best("EXIT").source if has_exit else None

    has_warn = ss.has("WARN", min_conf=p.warn_min_conf)
    has_pyramid = ss.has("PYRAMID", min_conf=p.pyramid_min_conf)
    best_pyramid_src = ss.best("PYRAMID").source if has_pyramid else None
    has_enter = ss.has("ENTER", min_conf=p.enter_min_conf)
    best_enter_src = ss.best("ENTER").source if has_enter else None

    bar = weekly_df.iloc[week_idx]
    bar_close = float(bar["close"])
    ma240_val = df_aug["ma_240"].iloc[week_idx] if "ma_240" in df_aug.columns else None
    ma240_ok = (
        not p.require_240ma_above
        or (pd.notna(ma240_val) and bar_close >= float(ma240_val))
    )

    sideways_block = (p.forbid_sideways_entry and ss.trend_type == "sideways")
    bearish_block = (p.forbid_bearish_alignment_entry and ss.bearish_alignment)
    book_gates_ok = (not sideways_block) and (not bearish_block)

    # Priority order
    if pos.is_open and has_exit:
        return ("EXIT", best_exit_src)

    if pos.is_open and pos.pending_warn:
        # Confirm WARN: just check previous bar close vs current
        prev_close = float(weekly_df["close"].iloc[week_idx - 1]) if week_idx > 0 else bar_close
        if bar_close < prev_close and pos.units > 0.25:
            return ("SCALE_OUT", "WARN 확정")

    if pos.is_open and has_pyramid and pos.units < 1.0 - 1e-6:
        return ("PYRAMID", best_pyramid_src)

    if (not pos.is_open) and has_enter and (not has_warn) and ma240_ok and book_gates_ok:
        return ("ENTER", best_enter_src)

    if pos.is_open and has_warn and not pos.pending_warn:
        return ("WARN_MARK", None)

    return ("HOLD", None)


def backtest_portfolio_v4(tickers: List[str],
                           params: Optional[PortfolioParams] = None,
                           verbose: bool = True,
                           use_cache: bool = True,
                           cache: Optional[SignalCache] = None,
                           n_jobs: int = 1) -> Dict:
    """Run portfolio-level V4 backtest over `tickers` universe.

    Args:
        use_cache: if True, read signals from SignalCache (build if missing).
        cache: pre-built SignalCache. If None and use_cache=True, default cache used.
    """
    p = params or PortfolioParams()
    tf_params = PARAMS_BY_TF.get("weekly", TFParams())
    if p.book_strict:
        tf_params = _book_strict_params(tf_params)

    # Strategy:
    #   - If use_cache: only load full OHLCV for tickers WITHOUT cache.
    #     Already-cached tickers reuse cached weekly bars (incl. close/MA).
    #   - For all tickers: load only daily close panel (much cheaper) for P&L.
    if cache is None and use_cache:
        cache = SignalCache()

    if use_cache:
        missing = [tk for tk in tickers
                    if not (cache._path(tk, "weekly").exists()
                            and cache._bars_path(tk, "weekly").exists())]
    else:
        missing = list(tickers)

    if missing:
        if verbose:
            print(f"[port-V4] loading {len(missing)} tickers without cache …")
        missing_dfs = _load_universe_prices(missing, p.start, p.end)
        if use_cache:
            if verbose:
                print(f"[port-V4] building signal cache for {len(missing_dfs)} tickers (n_jobs={n_jobs}) …")
            cache.build_for(list(missing_dfs.keys()), missing_dfs,
                             timeframes=("weekly",),
                             verbose=verbose, n_jobs=n_jobs)
    else:
        if verbose:
            print(f"[port-V4] all {len(tickers)} tickers cached, skip OHLCV load")

    # Get list of tickers that have cache (either pre-existing or just built)
    if use_cache:
        valid_tickers = [tk for tk in tickers
                          if cache._path(tk, "weekly").exists()
                          and cache._bars_path(tk, "weekly").exists()]
    else:
        valid_tickers = [tk for tk in missing if tk in missing_dfs]
    if verbose:
        print(f"[port-V4] {len(valid_tickers)} valid tickers")

    # Weekly bars: use cache if available, else build on the fly
    from app.book.trend import add_moving_averages
    ticker_weekly: Dict[str, pd.DataFrame] = {}
    ticker_weekly_aug: Dict[str, pd.DataFrame] = {}
    if use_cache:
        for tk in valid_tickers:
            bars = cache.get_bars(tk, "weekly")  # date-indexed
            if bars.empty:
                continue
            w = bars.reset_index().rename(columns={bars.index.name or "index": "date"})
            ticker_weekly[tk] = w
            ticker_weekly_aug[tk] = w  # bars already have ma_10, ma_240
    else:
        for tk in valid_tickers:
            df = missing_dfs.get(tk)
            if df is None:
                continue
            w = _resample_weekly(df)
            if len(w) < 70:
                continue
            ticker_weekly[tk] = w
            ticker_weekly_aug[tk] = add_moving_averages(w, [10, 240])

    if verbose:
        print(f"[port-V4] running weekly state machines …")

    # Daily close panel for portfolio mark-to-market (cheap batch load).
    if verbose:
        print(f"[port-V4] loading daily close panel ({len(valid_tickers)} tickers)…")
    close_panel = _load_daily_close_panel(valid_tickers, p.start, p.end)
    all_dates = list(close_panel.index)

    # Per-ticker per-Friday decision log
    decisions_by_date: Dict[pd.Timestamp, List[Tuple[str, str, str]]] = {}
    for tk, w in ticker_weekly.items():
        pos = Position(ticker=tk)
        df_aug = ticker_weekly_aug[tk]
        prev_close_v = None
        for i in range(len(w)):
            wk_date = pd.to_datetime(w["date"].iloc[i])
            if wk_date < p.start or wk_date > p.end:
                prev_close_v = float(w["close"].iloc[i])
                continue
            if i < 60:
                prev_close_v = float(w["close"].iloc[i])
                continue
            bar_close = float(w["close"].iloc[i])
            ma240_val = df_aug["ma_240"].iloc[i] if "ma_240" in df_aug.columns else None
            ma240_val = float(ma240_val) if pd.notna(ma240_val) else None

            if use_cache:
                ss = cache.get_signal_set(tk, "weekly", wk_date)
                if ss is None:
                    # No signals at this bar, but we still need pending_warn
                    # confirmation logic to run. Build an empty SignalSet.
                    ss = SignalSet(date=wk_date, close=bar_close)
                action, source = _decide_from_ss(
                    ss, pos, tf_params, bar_close,
                    prev_close_v if prev_close_v is not None else bar_close,
                    ma240_val,
                )
            else:
                action, source = _signal_decision(w, i, pos, tf_params, df_aug)
            prev_close_v = bar_close
            # Apply to local pos (we replay below for portfolio sizing)
            if action == "ENTER":
                pos.add_unit(wk_date, float(w["close"].iloc[i]),
                             0.25, "BUY", source or "", "")
            elif action == "PYRAMID":
                pos.add_unit(wk_date, float(w["close"].iloc[i]),
                             0.25, "PYRAMID", source or "", "")
            elif action == "SCALE_OUT":
                pos.reduce_unit(wk_date, float(w["close"].iloc[i]),
                                0.25, "SCALE_OUT", source or "", "")
                pos.pending_warn = False
            elif action == "EXIT":
                pos.reduce_unit(wk_date, float(w["close"].iloc[i]),
                                pos.units, "EXIT", source or "", "")
            elif action == "WARN_MARK":
                pos.pending_warn = True
                pos.pending_warn_date = wk_date

            if action != "HOLD":
                decisions_by_date.setdefault(wk_date, []).append(
                    (tk, action, source or "")
                )

    if verbose:
        n_dec = sum(len(v) for v in decisions_by_date.values())
        print(f"[port-V4] decisions logged: {n_dec}")

    # ----- Portfolio simulation -----
    # State: holdings = {ticker: shares}, cash = remaining equity
    equity = 1.0
    cash = 1.0
    holdings_shares: Dict[str, float] = {}
    holdings_units: Dict[str, float] = {}      # 0.25 / 0.5 / 0.75 / 1.0
    holdings_entry_costs: Dict[str, float] = {}  # weighted avg entry cost basis

    cost_pct = p.cost_bps / 10000.0

    eq_curve: List[Tuple[pd.Timestamp, float]] = []
    bench_curve: List[Tuple[pd.Timestamp, float]] = []

    # Benchmark: equal-weight buy-and-hold of all tickers w/ price on start date
    first_row = close_panel.iloc[0]
    valid_at_start = [tk for tk in valid_tickers
                       if tk in close_panel.columns
                       and pd.notna(first_row.get(tk))]
    bench_weight = 1.0 / max(len(valid_at_start), 1)
    bench_shares = {tk: bench_weight / float(first_row[tk])
                     for tk in valid_at_start}

    SLOT_VALUE = 1.0 / p.max_holdings  # 한 종목 full slot (= 4 units) 가치

    def unit_value_at_entry() -> float:
        return SLOT_VALUE * 0.25

    # Convert to numpy array once for fast iteration
    close_panel_np = close_panel.to_numpy()
    col_idx = {tk: i for i, tk in enumerate(close_panel.columns)}
    date_idx = {d: i for i, d in enumerate(close_panel.index)}

    def px_at(tk: str, d) -> Optional[float]:
        ci = col_idx.get(tk)
        di = date_idx.get(d)
        if ci is None or di is None:
            return None
        v = close_panel_np[di, ci]
        if v != v:  # NaN check
            return None
        return float(v)

    for d in all_dates:
        # Apply decisions on this date (week endings = Fridays)
        if d in decisions_by_date:
            for tk, action, source in decisions_by_date[d]:
                px = px_at(tk, d)
                if px is None:
                    continue
                if action == "ENTER":
                    if len(holdings_units) >= p.max_holdings:
                        continue  # portfolio full
                    target_value = unit_value_at_entry() * equity
                    shares = target_value / px
                    fee = target_value * cost_pct
                    cash -= target_value + fee
                    holdings_shares[tk] = shares
                    holdings_units[tk] = 0.25
                    holdings_entry_costs[tk] = px
                elif action == "PYRAMID":
                    if tk not in holdings_units:
                        continue
                    target_value = unit_value_at_entry() * equity
                    shares = target_value / px
                    fee = target_value * cost_pct
                    cash -= target_value + fee
                    # Update weighted-avg entry cost
                    old_shares = holdings_shares[tk]
                    old_cost = holdings_entry_costs[tk] * old_shares
                    new_total = old_cost + px * shares
                    holdings_shares[tk] = old_shares + shares
                    holdings_entry_costs[tk] = new_total / holdings_shares[tk]
                    holdings_units[tk] += 0.25
                elif action == "SCALE_OUT":
                    if tk not in holdings_units:
                        continue
                    # sell 1 unit worth = current_value * (0.25 / units_current)
                    frac = 0.25 / max(holdings_units[tk], 1e-6)
                    sell_shares = holdings_shares[tk] * frac
                    sell_value = sell_shares * px
                    fee = sell_value * cost_pct
                    cash += sell_value - fee
                    holdings_shares[tk] -= sell_shares
                    holdings_units[tk] -= 0.25
                    if holdings_units[tk] <= 0.01:
                        del holdings_shares[tk]
                        del holdings_units[tk]
                        del holdings_entry_costs[tk]
                elif action == "EXIT":
                    if tk not in holdings_units:
                        continue
                    sell_value = holdings_shares[tk] * px
                    fee = sell_value * cost_pct
                    cash += sell_value - fee
                    del holdings_shares[tk]
                    del holdings_units[tk]
                    del holdings_entry_costs[tk]

        # Daily mark-to-market (vectorized via close_panel)
        port_value = cash
        for tk, sh in holdings_shares.items():
            px = px_at(tk, d)
            if px is not None:
                port_value += sh * px
        equity = port_value

        bench_val = 0.0
        for tk, sh in bench_shares.items():
            px = px_at(tk, d)
            if px is not None:
                bench_val += sh * px

        eq_curve.append((d, equity))
        bench_curve.append((d, bench_val))

    eq_s = pd.Series([v for _, v in eq_curve],
                      index=[d for d, _ in eq_curve])
    bench_s = pd.Series([v for _, v in bench_curve],
                         index=[d for d, _ in bench_curve])
    bench_s = bench_s / bench_s.iloc[0]

    metrics = _compute_metrics(eq_s, bench_s)
    if verbose:
        print(f"[port-V4] DONE. CAGR {metrics.cagr*100:+.2f}%  "
              f"vs Bench {metrics.bench_cagr*100:+.2f}%  "
              f"α {metrics.alpha*100:+.2f}%p  Sharpe {metrics.sharpe:.2f}  "
              f"MDD {metrics.max_drawdown*100:.1f}%")

    return {
        "equity_curve": eq_s,
        "benchmark_curve": bench_s,
        "metrics": metrics.__dict__,
        "n_decisions": sum(len(v) for v in decisions_by_date.values()),
        "n_tickers_in_universe": len(valid_tickers),
        "params": {
            "start": str(p.start.date()), "end": str(p.end.date()),
            "max_holdings": p.max_holdings,
            "decision_freq": p.decision_freq,
            "book_strict": p.book_strict,
            "cost_bps": p.cost_bps,
        },
    }


def _compute_metrics(eq: pd.Series, bench: pd.Series) -> PortfolioMetrics:
    days = (eq.index[-1] - eq.index[0]).days
    years = max(days / 365.25, 1e-6)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    bench_total = float(bench.iloc[-1] / bench.iloc[0] - 1)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    bench_cagr = float((bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1)

    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    vol = float(rets.std() * np.sqrt(252)) if len(rets) > 1 else 0.0
    sharpe = (cagr - 0.0) / vol if vol > 0 else 0.0

    excess = (rets - bench_rets.reindex(rets.index).fillna(0)).dropna()
    info_ratio = (
        (excess.mean() * 252) / (excess.std() * np.sqrt(252))
        if excess.std() > 0 else 0.0
    )

    peak = eq.cummax()
    dd = (eq / peak - 1).min()
    mdd = float(dd) if not np.isnan(dd) else 0.0

    win_daily = float((rets > 0).mean()) if len(rets) > 0 else 0.0

    return PortfolioMetrics(
        cagr=cagr, bench_cagr=bench_cagr,
        alpha=cagr - bench_cagr,
        vol_annual=vol, sharpe=sharpe, info_ratio=float(info_ratio),
        max_drawdown=mdd, win_rate_daily=win_daily,
        total_return=total, bench_total_return=bench_total,
        n_days=int(len(eq)),
    )
