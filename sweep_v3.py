"""Quick hyperparam sweep on existing v3 panel — 5y backtest each combo."""
import json, time
import pandas as pd
from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3

panel = pd.read_parquet("models_store/feature_panel_v3.parquet")
print(f"Panel: {panel.shape}  ({panel['date'].min()} → {panel['date'].max()})", flush=True)

combos = [
    ("baseline (no brake/cap)",  -1.0, 1.0),
    ("v3 default",                -0.15, 0.25),
    ("looser brake",              -0.20, 0.25),
    ("tighter brake",             -0.10, 0.30),
    ("loose both",                -0.25, 0.35),
    ("cap only",                  -1.0, 0.30),
]

results = []
for name, dd, sc in combos:
    t0 = time.time()
    bt = run_wf_v3(
        # Shorter test window + shorter training window for speed
        WFv3Params(start="2022-01-01", end="2024-12-31",
                   train_start="2017-01-01", rebalance_n=21,
                   top_k=20, cost_bps=10, slippage_bps=5,
                   sector_cap=sc, drawdown_brake=dd,
                   use_rank_target=True, feature_suffix="_sn",
                   boost_rounds=200),
        panel=panel, verbose=False)
    m = bt["metrics"]
    elapsed = time.time() - t0
    row = {
        "name": name, "dd_brake": dd, "sector_cap": sc,
        "cagr": m["cagr"], "alpha": m["alpha"],
        "sharpe": m["sharpe"], "ir": m["info_ratio"],
        "max_drawdown": m["max_drawdown"], "vol": m["vol_annual"],
        "elapsed": elapsed,
    }
    results.append(row)
    print(f"  {name:25s} dd={dd:+.2f} sc={sc:.2f} | "
          f"CAGR={m['cagr']*100:+.2f}%  Sharpe={m['sharpe']:+.2f}  "
          f"MDD={m['max_drawdown']*100:+.2f}%  alpha={m['alpha']*100:+.2f}%  "
          f"({elapsed:.0f}s)", flush=True)

with open("models_store/hyperparam_sweep.json", "w") as f:
    json.dump(results, f, default=str, indent=2)

print("\n" + "=" * 70)
print(" Top by Sharpe:")
print("=" * 70)
results.sort(key=lambda r: r["sharpe"], reverse=True)
for r in results:
    print(f"  {r['name']:25s} | CAGR={r['cagr']*100:+.2f}%  "
          f"Sharpe={r['sharpe']:+.2f}  MDD={r['max_drawdown']*100:+.2f}%  "
          f"alpha={r['alpha']*100:+.2f}%")
