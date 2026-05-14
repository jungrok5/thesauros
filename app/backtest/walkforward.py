"""Walk-forward backtest using a LightGBM model retrained at each step.

Loop:
  for each rebalance date t:
    1. Train on all panel rows with date <= t - embargo (PIT-safe).
    2. Predict scores for date == t.
    3. Pick top-K stocks (long-only, equal-weight).
    4. Hold for `rebalance_n` days, then repeat.

Costs: COST_BPS per side + SLIPPAGE_BPS per side, applied on turnover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from app.config import (
    COST_BPS, EMBARGO_DAYS, FORWARD_HORIZON, RF_ANNUAL,
    SLIPPAGE_BPS, TRADING_DAYS,
)
from app.features.pipeline import ALL_FEATURES, build_panel, load_prices_wide


@dataclass
class WFParams:
    start: str = "2017-01-01"
    end: Optional[str] = None
    train_start: str = "2014-01-01"
    rebalance_n: int = 21
    top_k: int = 20
    cost_bps: float = COST_BPS
    slippage_bps: float = SLIPPAGE_BPS
    feature_cols: List[str] = field(default_factory=lambda: [c + "_rk" for c in ALL_FEATURES])
    min_train_rows: int = 5000
    lgb_params: dict = field(default_factory=lambda: {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbose": -1,
    })
    boost_rounds: int = 300


def _metrics(equity: pd.Series, bench: pd.Series) -> Dict:
    if equity.empty:
        return {}
    rets = equity.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    days = len(rets)
    years = days / TRADING_DAYS if days else 1.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    bench_cagr = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    vol_ann = rets.std() * np.sqrt(TRADING_DAYS) if len(rets) > 1 else 0.0
    sharpe = (cagr - RF_ANNUAL) / vol_ann if vol_ann > 0 else 0.0
    cum = (1 + rets).cumprod()
    peak = cum.cummax()
    mdd = float((cum / peak - 1).min()) if len(cum) else 0.0
    info = (cagr - bench_cagr) / max((rets - bench_rets.reindex(rets.index, fill_value=0)).std() * np.sqrt(TRADING_DAYS), 1e-9)
    return {
        "cagr": float(cagr),
        "bench_cagr": float(bench_cagr),
        "alpha": float(cagr - bench_cagr),
        "vol_annual": float(vol_ann),
        "sharpe": float(sharpe),
        "info_ratio": float(info),
        "max_drawdown": mdd,
        "win_rate_daily": float((rets > 0).mean()),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "bench_total_return": float(bench.iloc[-1] / bench.iloc[0] - 1),
        "n_days": int(days),
    }


def run_walkforward(params: WFParams,
                    panel: Optional[pd.DataFrame] = None,
                    verbose: bool = True) -> Dict:
    """Returns dict with equity_curve, benchmark, metrics, holdings, ic_history."""
    if panel is None:
        panel = build_panel(start=params.train_start, end=params.end,
                            rebalance_n=params.rebalance_n, verbose=verbose)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)

    # Returns matrix
    prices = load_prices_wide(start=params.train_start, end=params.end)

    # Walk-forward dates: panel dates >= start
    rb_dates = sorted(panel["date"].unique())
    rb_dates = [d for d in rb_dates if d >= pd.Timestamp(params.start)]
    if not rb_dates:
        return {"error": "No rebalance dates after start"}

    # Pre-compute daily returns of universe
    rets = prices.pct_change().fillna(0)

    cost = (params.cost_bps + params.slippage_bps) / 10_000.0

    equity = 1.0
    bench_eq = 1.0
    weights: Dict[str, float] = {}
    bench_weights: Optional[pd.Series] = None
    eq_curve = []
    bench_curve = []
    holdings_log: List[Dict] = []
    ic_history: List[Dict] = []

    # We need a dense daily walk inside the rebalance windows
    daily_dates = list(prices.index)
    daily_dates = [d for d in daily_dates if d >= pd.Timestamp(params.start)
                   and (params.end is None or d <= pd.Timestamp(params.end))]
    if not daily_dates:
        return {"error": "No daily dates"}

    # Initial benchmark: equal-weight across tickers with non-NaN price at start
    init_valid = prices.loc[daily_dates[0]].dropna().index.tolist()
    if init_valid:
        bench_weights = pd.Series(0.0, index=prices.columns)
        bench_weights[init_valid] = 1.0 / len(init_valid)

    # Train+predict at each rebalance, accumulate daily returns between
    next_rb = 0
    for d in daily_dates:
        # Hit a rebalance?
        if next_rb < len(rb_dates) and d >= rb_dates[next_rb]:
            t = rb_dates[next_rb]
            # 1) Build training set: rows with date <= t - embargo, target known.
            cutoff = t - pd.Timedelta(days=EMBARGO_DAYS + FORWARD_HORIZON)
            train = panel[panel["date"] <= cutoff].dropna(subset=["y_fwd"]).copy()
            test = panel[panel["date"] == t].copy()
            if len(train) >= params.min_train_rows and len(test) > 0:
                Xtr = train[params.feature_cols]
                ytr = train["y_fwd"].astype(float)
                Xte = test[params.feature_cols]
                model = lgb.train(params.lgb_params,
                                  lgb.Dataset(Xtr, label=ytr),
                                  num_boost_round=params.boost_rounds)
                preds = model.predict(Xte)
                test["pred"] = preds
                # IC vs realized fwd return (when known)
                if test["y_fwd"].notna().sum() > 5:
                    ic = float(spearmanr(test["pred"], test["y_fwd"].fillna(0))[0])
                else:
                    ic = float("nan")
                ic_history.append({"date": str(t.date()), "ic": ic,
                                   "n_train": len(train), "n_test": len(test)})
                # Top-K long-only equal-weight
                top = test.nlargest(params.top_k, "pred")["ticker"].tolist()
                new_w = {tk: 0.0 for tk in prices.columns}
                w_each = 1.0 / max(len(top), 1)
                for tk in top:
                    new_w[tk] = w_each
                turnover = sum(abs(new_w[tk] - weights.get(tk, 0.0)) for tk in prices.columns)
                equity *= (1.0 - turnover * cost)
                weights = new_w
                holdings_log.append({"date": str(t.date()), "tickers": top,
                                     "scores": [float(x) for x in test.nlargest(params.top_k, "pred")["pred"].values]})
            next_rb += 1

        # Daily P&L
        day_ret = rets.loc[d] if d in rets.index else None
        if day_ret is not None and weights:
            port_ret = sum(weights.get(tk, 0.0) * float(day_ret.get(tk, 0.0))
                           for tk in weights)
            equity *= (1.0 + port_ret)
        if bench_weights is not None and day_ret is not None:
            bench_ret = float((bench_weights * day_ret).sum())
            bench_eq *= (1.0 + bench_ret)
        eq_curve.append((d, equity))
        bench_curve.append((d, bench_eq))

    eq_s = pd.Series([v for _, v in eq_curve], index=[d for d, _ in eq_curve])
    bench_s = pd.Series([v for _, v in bench_curve], index=[d for d, _ in bench_curve])

    return {
        "equity_curve": eq_s,
        "benchmark_curve": bench_s,
        "metrics": _metrics(eq_s, bench_s),
        "holdings": holdings_log,
        "ic_history": ic_history,
        "params": {
            "start": params.start, "end": params.end, "top_k": params.top_k,
            "rebalance_n": params.rebalance_n,
            "cost_bps": params.cost_bps, "slippage_bps": params.slippage_bps,
        },
    }
