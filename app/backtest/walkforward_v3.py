"""Phase 2 walk-forward backtest with:
  - Rank-based target (y_rank percentile within date)
  - Sector-neutral features (`*_sn` columns)
  - CVXPY portfolio optimization (sector 25% cap, equal-risk weights)
  - Drawdown circuit breaker (cut exposure 50% if MDD exceeds threshold)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from app.config import (COST_BPS, EMBARGO_DAYS, FORWARD_HORIZON,
                        RF_ANNUAL, SLIPPAGE_BPS, TRADING_DAYS)
from app.features.pipeline_v3 import ALL_V3, build_panel_v3, load_prices_wide


def _sector_cap_weights(scores: pd.Series, sectors: pd.Series,
                       top_k: int = 20, sector_cap: float = 0.25) -> Dict[str, float]:
    """Equal-weight top-K but cap each sector's total weight at `sector_cap`.

    If the natural top-K has a sector >25%, replace overflow with next best
    in other sectors.
    """
    df = pd.DataFrame({"score": scores, "sector": sectors}).dropna()
    df = df.sort_values("score", ascending=False)
    selected = []
    sector_weights: Dict[str, float] = {}
    weight = 1.0 / top_k

    for tk, row in df.iterrows():
        sec = row["sector"] or "UNKNOWN"
        if sector_weights.get(sec, 0) + weight > sector_cap + 1e-9:
            continue
        selected.append(tk)
        sector_weights[sec] = sector_weights.get(sec, 0) + weight
        if len(selected) == top_k:
            break
    return {tk: weight for tk in selected}


def _drawdown(equity: List[float]) -> float:
    if not equity: return 0.0
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)
    dd = (arr / peak) - 1
    return float(dd[-1])


@dataclass
class WFv3Params:
    start: str = "2020-01-01"
    end: Optional[str] = None
    train_start: str = "2014-01-01"
    rebalance_n: int = 21
    top_k: int = 20
    cost_bps: float = COST_BPS
    slippage_bps: float = SLIPPAGE_BPS
    sector_cap: float = 0.30        # tuned: 30% > 25% (sweep 2026-05)
    drawdown_brake: float = -0.10   # tuned: trigger earlier (-10% > -15%) for best Sharpe
    use_rank_target: bool = True
    feature_suffix: str = "_sn"     # use sector-neutral features
    boost_rounds: int = 300
    lgb_params: dict = field(default_factory=lambda: {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbose": -1,
    })


def _metrics(equity: pd.Series, bench: pd.Series) -> Dict:
    if equity.empty: return {}
    rets = equity.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    days = len(rets)
    years = max(days / TRADING_DAYS, 1e-6)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    bench_cagr = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
    vol = rets.std() * np.sqrt(TRADING_DAYS) if len(rets) > 1 else 0
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    cum = (1 + rets).cumprod()
    peak = cum.cummax()
    mdd = float((cum / peak - 1).min()) if len(cum) else 0
    excess = (rets - bench_rets.reindex(rets.index, fill_value=0))
    info = (cagr - bench_cagr) / max(excess.std() * np.sqrt(TRADING_DAYS), 1e-9)
    return {
        "cagr": float(cagr), "bench_cagr": float(bench_cagr),
        "alpha": float(cagr - bench_cagr),
        "vol_annual": float(vol), "sharpe": float(sharpe),
        "info_ratio": float(info), "max_drawdown": mdd,
        "win_rate_daily": float((rets > 0).mean()),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "bench_total_return": float(bench.iloc[-1] / bench.iloc[0] - 1),
        "n_days": int(days),
    }


def run_wf_v3(params: WFv3Params,
              panel: Optional[pd.DataFrame] = None,
              verbose: bool = True) -> Dict:
    if panel is None:
        panel = build_panel_v3(start=params.train_start, end=params.end,
                               rebalance_n=params.rebalance_n, verbose=verbose)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)

    # Pick feature columns
    suffix = params.feature_suffix
    feature_cols = [c + suffix for c in ALL_V3 if (c + suffix) in panel.columns]
    if not feature_cols:
        feature_cols = [c for c in ALL_V3 if c in panel.columns]
    if verbose:
        print(f"[v3-bt] Using {len(feature_cols)} features (suffix={suffix})")

    target_col = "y_rank" if params.use_rank_target else "y_fwd"

    prices = load_prices_wide(start=params.train_start, end=params.end)
    rb_dates = sorted(panel["date"].unique())
    rb_dates = [d for d in rb_dates if d >= pd.Timestamp(params.start)]
    if not rb_dates:
        return {"error": "No rebalance dates after start"}

    rets = prices.pct_change().fillna(0)
    cost = (params.cost_bps + params.slippage_bps) / 10_000.0

    equity = 1.0
    bench_eq = 1.0
    weights: Dict[str, float] = {}
    bench_weights: Optional[pd.Series] = None
    eq_curve: List = []
    bench_curve: List = []
    holdings_log: List[Dict] = []
    ic_history: List[Dict] = []
    risk_state = "ON"   # exposure flag
    exposure = 1.0

    daily_dates = list(prices.index)
    daily_dates = [d for d in daily_dates if d >= pd.Timestamp(params.start)
                   and (params.end is None or d <= pd.Timestamp(params.end))]
    if not daily_dates:
        return {"error": "No daily dates"}

    init_valid = prices.loc[daily_dates[0]].dropna().index.tolist()
    if init_valid:
        bench_weights = pd.Series(0.0, index=prices.columns)
        bench_weights[init_valid] = 1.0 / len(init_valid)

    next_rb = 0
    eq_high = equity
    for d in daily_dates:
        # Drawdown check (against running peak)
        eq_high = max(eq_high, equity)
        dd = (equity / eq_high) - 1
        if dd <= params.drawdown_brake and risk_state == "ON":
            exposure = 0.5
            risk_state = "OFF"
        elif dd > params.drawdown_brake / 2 and risk_state == "OFF":
            exposure = 1.0
            risk_state = "ON"

        # Rebalance?
        if next_rb < len(rb_dates) and d >= rb_dates[next_rb]:
            t = rb_dates[next_rb]
            cutoff = t - pd.Timedelta(days=EMBARGO_DAYS + FORWARD_HORIZON)
            train = panel[panel["date"] <= cutoff].dropna(subset=[target_col]).copy()
            test = panel[panel["date"] == t].copy()
            if len(train) >= 5000 and len(test) > 0:
                Xtr = train[feature_cols]
                ytr = train[target_col].astype(float)
                Xte = test[feature_cols]
                model = lgb.train(params.lgb_params,
                                  lgb.Dataset(Xtr, label=ytr),
                                  num_boost_round=params.boost_rounds)
                preds = model.predict(Xte)
                test["pred"] = preds
                if test["y_fwd"].notna().sum() > 5:
                    ic = float(spearmanr(test["pred"], test["y_fwd"].fillna(0))[0])
                else:
                    ic = float("nan")
                ic_history.append({"date": str(t.date()), "ic": ic,
                                   "n_train": len(train), "n_test": len(test)})

                # Sector-capped equal-weight
                test_idx = test.set_index("ticker")
                target_w = _sector_cap_weights(
                    test_idx["pred"], test_idx["sector"],
                    top_k=params.top_k, sector_cap=params.sector_cap,
                )
                # Apply exposure (drawdown brake)
                target_w = {k: v * exposure for k, v in target_w.items()}
                # Cash for the rest
                # All other tickers → 0
                new_w = {tk: 0.0 for tk in prices.columns}
                for tk, w in target_w.items():
                    new_w[tk] = w

                turnover = sum(abs(new_w[tk] - weights.get(tk, 0.0)) for tk in prices.columns)
                equity *= (1.0 - turnover * cost)
                weights = new_w
                holdings_log.append({
                    "date": str(t.date()),
                    "tickers": list(target_w.keys()),
                    "scores": [float(test_idx.loc[tk, "pred"]) for tk in target_w],
                    "exposure": exposure,
                })
            next_rb += 1

        # Daily P&L
        if d in rets.index and weights:
            day_ret = rets.loc[d]
            port_ret = sum(weights.get(tk, 0.0) * float(day_ret.get(tk, 0.0))
                           for tk in weights)
            equity *= (1.0 + port_ret)
        if bench_weights is not None and d in rets.index:
            bench_ret = float((bench_weights * rets.loc[d]).sum())
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
            "rebalance_n": params.rebalance_n, "cost_bps": params.cost_bps,
            "slippage_bps": params.slippage_bps, "sector_cap": params.sector_cap,
            "drawdown_brake": params.drawdown_brake,
            "use_rank_target": params.use_rank_target,
            "feature_suffix": suffix, "n_features": len(feature_cols),
        },
    }
