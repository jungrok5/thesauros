"""Rebuild v3 panel with extended history, retrain, run long backtest."""
import time
import pandas as pd
import joblib

from app.config import MODEL_DIR
from app.features.pipeline_v3 import ALL_V3, build_panel_v3
from app.model.lgbm import fit_lgbm
from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3

LOG = open("models_store/rebuild_log.txt", "w", encoding="utf-8")

def log(msg):
    print(msg, flush=True)
    LOG.write(str(msg) + "\n")
    LOG.flush()


# 1) Build panel from 2010
log("=" * 60)
log("STEP 1: Build v3 panel from 2010")
log("=" * 60)
t0 = time.time()
panel = build_panel_v3(start="2010-01-01", rebalance_n=21, verbose=False)
log(f"Built {len(panel):,} rows × {panel.shape[1]} cols in {time.time()-t0:.0f}s")
log(f"Date range: {panel['date'].min()} → {panel['date'].max()}")
log(f"Tickers: {panel['ticker'].nunique()}")
panel.to_parquet(MODEL_DIR / "feature_panel_v3.parquet", index=False)

# 2) Retrain
log("\n" + "=" * 60)
log("STEP 2: Retrain v3 with extended history")
log("=" * 60)
feat_sn = [c + "_sn" for c in ALL_V3 if (c + "_sn") in panel.columns]
log(f"Using {len(feat_sn)} sector-neutral features")
panel_t = panel.dropna(subset=["y_rank"]).copy()
log(f"After target dropna: {len(panel_t):,} rows")

t0 = time.time()
res = fit_lgbm(panel_t, feat_sn, target_col="y_rank", n_splits=5,
               params={"num_leaves": 63, "min_data_in_leaf": 100,
                       "learning_rate": 0.05, "lambda_l2": 1.0})
log(f"Trained in {time.time()-t0:.0f}s")
log(f"OOF IC mean: {res['oof_ic_mean']:+.4f} std: {res['oof_ic_std']:.4f}")

joblib.dump({
    "model": res["model"], "feature_cols": feat_sn,
    "oof_ic_mean": res["oof_ic_mean"], "fold_metrics": res["fold_metrics"],
    "target_col": "y_rank", "feature_suffix": "_sn",
}, "models_store/lgbm_v3.pkl")

log("\nTop 15 features:")
log(res["feature_importance"].head(15).to_string(index=False))

# 3) Long backtest
log("\n" + "=" * 60)
log("STEP 3: Walk-forward backtest 2012-2024 (with 2018-Q4, 2020 covid, 2022)")
log("=" * 60)
t0 = time.time()
bt_long = run_wf_v3(
    WFv3Params(start="2012-01-01", end="2024-12-31",
               train_start="2010-01-01", rebalance_n=21,
               top_k=20, cost_bps=10, slippage_bps=5,
               sector_cap=0.25, drawdown_brake=-0.15,
               use_rank_target=True, feature_suffix="_sn"),
    panel=panel, verbose=False)
log(f"Backtest done in {time.time()-t0:.0f}s")

m = bt_long["metrics"]
log("\nLong-term v3 metrics (2012-2024):")
for k, v in m.items():
    log(f"  {k}: {v}")

# 4) Hyper-param sweep on DD brake & sector cap
log("\n" + "=" * 60)
log("STEP 4: Hyperparam sweep — find best DD brake / sector cap")
log("=" * 60)

results = []
# Smaller sweep: 6 pairs covering the key trade-offs
combos = [
    (-1.0, 1.0),    # baseline: no brake, no cap (≈ v2 with v3 features)
    (-0.15, 0.25),  # current v3 default
    (-0.20, 0.25),  # looser brake
    (-0.10, 0.30),  # tight brake, looser cap
    (-0.25, 0.35),  # loose both
    (-1.0, 0.30),   # cap only, no brake
]
for dd, sc in combos:
    if True:
        t0 = time.time()
        bt = run_wf_v3(
            WFv3Params(start="2014-01-01", end="2024-12-31",
                       train_start="2010-01-01", rebalance_n=21,
                       top_k=20, cost_bps=10, slippage_bps=5,
                       sector_cap=sc, drawdown_brake=dd,
                       use_rank_target=True, feature_suffix="_sn"),
            panel=panel, verbose=False)
        m = bt["metrics"]
        results.append({
            "dd_brake": dd, "sector_cap": sc,
            "cagr": m["cagr"], "sharpe": m["sharpe"],
            "mdd": m["max_drawdown"], "alpha": m["alpha"],
            "ir": m["info_ratio"], "vol": m["vol_annual"],
            "elapsed_s": time.time() - t0,
        })
        log(f"  dd={dd:5.2f} sc={sc:.2f} → CAGR={m['cagr']*100:+.1f}% Sharpe={m['sharpe']:+.2f} MDD={m['mdd']*100:+.1f}% alpha={m['alpha']*100:+.1f}%")

import json
with open("models_store/hyperparam_sweep.json", "w") as f:
    json.dump(results, f, default=str)

# Sort by Sharpe
results.sort(key=lambda r: r["sharpe"], reverse=True)
log("\nTop 5 by Sharpe:")
for r in results[:5]:
    log(f"  dd={r['dd_brake']:.2f} sc={r['sector_cap']:.2f} | "
        f"CAGR={r['cagr']*100:+.2f}% Sharpe={r['sharpe']:+.2f} MDD={r['mdd']*100:+.2f}% alpha={r['alpha']*100:+.2f}%")

log("\n" + "=" * 60)
log("DONE")
LOG.close()
