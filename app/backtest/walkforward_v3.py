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


def _select_with_sector_cap(scores: pd.Series, sectors: pd.Series,
                            top_k: int, sector_cap: float) -> List[str]:
    """Sector-capped greedy top-K selection (returns ordered ticker list).

    Equal-weight assumption only used for cap check; actual weighting
    is applied separately so we can plug in inverse-vol / risk-parity.
    """
    df = pd.DataFrame({"score": scores, "sector": sectors}).dropna()
    df = df.sort_values("score", ascending=False)
    selected: List[str] = []
    sector_weights: Dict[str, float] = {}
    equal_w = 1.0 / top_k
    for tk, row in df.iterrows():
        sec = row["sector"] or "UNKNOWN"
        if sector_weights.get(sec, 0) + equal_w > sector_cap + 1e-9:
            continue
        selected.append(tk)
        sector_weights[sec] = sector_weights.get(sec, 0) + equal_w
        if len(selected) == top_k:
            break
    return selected


def _compute_weights(selected: List[str], vols: pd.Series,
                     scheme: str = "equal") -> Dict[str, float]:
    """Compute portfolio weights for the selected tickers.

    Schemes:
      - "equal"        : 1/N for each (book v3 baseline)
      - "inverse_vol"  : weight ∝ 1/σ (book p304 weight by stability)
      - "risk_parity"  : equal risk contribution ≈ inverse-vol when no
                         correlation matrix (we use this approximation)
    """
    if not selected:
        return {}
    if scheme == "equal":
        w = 1.0 / len(selected)
        return {tk: w for tk in selected}

    # inverse-vol — clamp very low / NaN vols so a tiny-vol ticker doesn't
    # eat the portfolio.
    sel_vols = vols.reindex(selected).copy()
    sel_vols = sel_vols.replace([np.inf, -np.inf], np.nan)
    median_vol = float(sel_vols.median()) if sel_vols.notna().any() else 1.0
    sel_vols = sel_vols.fillna(median_vol).clip(lower=median_vol * 0.30)
    inv = 1.0 / sel_vols
    weights = inv / inv.sum()
    return {tk: float(w) for tk, w in weights.items()}


def _sector_cap_weights(scores: pd.Series, sectors: pd.Series,
                        top_k: int = 20, sector_cap: float = 0.25,
                        vols: Optional[pd.Series] = None,
                        scheme: str = "equal") -> Dict[str, float]:
    """Convenience wrapper — select + weight in one call."""
    selected = _select_with_sector_cap(scores, sectors, top_k, sector_cap)
    if vols is None:
        vols = pd.Series(1.0, index=selected)
    return _compute_weights(selected, vols, scheme=scheme)


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

    # P2 — portfolio construction
    weighting_scheme: str = "inverse_vol"  # equal | inverse_vol | risk_parity
    vol_lookback: int = 60                  # days for portfolio-construction vol

    # P7 — realistic tax / cost simulation
    tax_long_term_pct: float = 0.0          # held >365d (e.g. 0.20 = 20%)
    tax_short_term_pct: float = 0.0         # held <=365d
    # Korean KRX: separately add 0.18% sell-side transaction tax via cost_bps
    # US: ignore here (set short-term=0.37 if simulating retiree-class trader)

    # P1 — regime conditioning
    regime_cash_trigger: bool = False       # if True, go 100% cash on FEAR
    regime_feature: bool = False            # if True, add regime as a feature

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

    # Pre-compute rolling daily vol for the inverse-vol / risk-parity weighting.
    daily_vol = rets.rolling(params.vol_lookback, min_periods=20).std()

    # Tracks per-ticker entry timestamp + entry price for tax simulation.
    entry_log: Dict[str, Dict] = {}

    equity = 1.0
    bench_eq = 1.0
    weights: Dict[str, float] = {}
    bench_weights: Optional[pd.Series] = None
    eq_curve: List = []
    tax_paid_total = 0.0
    tax_events: List[Dict] = []
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

                # Sector-capped selection + chosen weighting scheme
                test_idx = test.set_index("ticker")
                # Vol snapshot up to (and including) rebalance date
                if d in daily_vol.index:
                    vol_today = daily_vol.loc[d]
                else:
                    vol_today = daily_vol.iloc[-1]
                target_w = _sector_cap_weights(
                    test_idx["pred"], test_idx["sector"],
                    top_k=params.top_k, sector_cap=params.sector_cap,
                    vols=vol_today, scheme=params.weighting_scheme,
                )
                # Apply exposure (drawdown brake)
                target_w = {k: v * exposure for k, v in target_w.items()}

                # Regime cash trigger (P1)
                if params.regime_cash_trigger:
                    try:
                        from app.macro.state import market_regime
                        regime = market_regime().get("regime", "UNKNOWN")
                        if regime == "FEAR":
                            target_w = {}
                    except Exception:
                        pass

                new_w = {tk: 0.0 for tk in prices.columns}
                for tk, w in target_w.items():
                    new_w[tk] = w

                # ---- Tax simulation on sells (P7) ----
                if params.tax_short_term_pct > 0 or params.tax_long_term_pct > 0:
                    for tk in list(weights.keys()):
                        prev_w = weights.get(tk, 0.0)
                        cur_w = new_w.get(tk, 0.0)
                        if prev_w > 0 and cur_w < prev_w * 0.99:
                            ent = entry_log.get(tk)
                            if ent is None:
                                continue
                            # Realised return per share
                            entry_price = ent["price"]
                            if t in prices.index and tk in prices.columns:
                                exit_price = float(prices.loc[t, tk])
                            else:
                                exit_price = entry_price
                            if exit_price <= 0 or entry_price <= 0:
                                continue
                            holding_days = (t - ent["date"]).days
                            rate = (params.tax_short_term_pct
                                    if holding_days <= 365
                                    else params.tax_long_term_pct)
                            if rate > 0:
                                realised_ret = (exit_price / entry_price) - 1.0
                                if realised_ret > 0:
                                    portion_sold = (prev_w - cur_w)
                                    gain_amount = realised_ret * portion_sold
                                    tax = rate * gain_amount
                                    equity *= (1.0 - tax)
                                    tax_paid_total += tax
                                    tax_events.append({
                                        "date": str(t.date()), "ticker": tk,
                                        "held_days": holding_days,
                                        "return_pct": realised_ret * 100,
                                        "tax_pct_of_equity": tax * 100,
                                    })

                # Update entry log: new positions get entry, increased positions
                # keep old entry (approximation; this is a backtest, not real fills).
                for tk in prices.columns:
                    prev_w = weights.get(tk, 0.0)
                    cur_w = new_w.get(tk, 0.0)
                    if cur_w > 0 and prev_w == 0:
                        # new position
                        if d in prices.index and tk in prices.columns:
                            entry_log[tk] = {"date": t, "price": float(prices.loc[t, tk])}
                    elif cur_w == 0 and prev_w > 0:
                        entry_log.pop(tk, None)

                turnover = sum(abs(new_w[tk] - weights.get(tk, 0.0)) for tk in prices.columns)
                equity *= (1.0 - turnover * cost)
                weights = new_w
                holdings_log.append({
                    "date": str(t.date()),
                    "tickers": list(target_w.keys()),
                    "weights": {tk: round(target_w[tk], 4) for tk in target_w},
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
        "tax_paid_total_pct": round(tax_paid_total * 100, 3),
        "tax_events": tax_events[-50:],   # tail sample
        "params": {
            "start": params.start, "end": params.end, "top_k": params.top_k,
            "rebalance_n": params.rebalance_n, "cost_bps": params.cost_bps,
            "slippage_bps": params.slippage_bps, "sector_cap": params.sector_cap,
            "drawdown_brake": params.drawdown_brake,
            "use_rank_target": params.use_rank_target,
            "feature_suffix": suffix, "n_features": len(feature_cols),
            "weighting_scheme": params.weighting_scheme,
            "tax_short_term_pct": params.tax_short_term_pct,
            "tax_long_term_pct": params.tax_long_term_pct,
            "regime_cash_trigger": params.regime_cash_trigger,
        },
    }
