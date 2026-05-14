"""Standalone v2 vs v3 comparison. Writes progress to a log file
that we can tail for status updates.
"""
import json
import math
import sys
import time

import pandas as pd

from app.backtest.walkforward import WFParams, run_walkforward
from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3

LOG = open("models_store/compare_log.txt", "w", encoding="utf-8")


def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(x) for x in o]
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else o
    return o


def fpct(x): return f"{x*100:+.2f}%" if x is not None else "—"
def fnum(x, d=2): return f"{x:+.{d}f}" if x is not None else "—"


log("Loading panels...")
panel_v2 = pd.read_parquet("models_store/feature_panel.parquet")
panel_v3 = pd.read_parquet("models_store/feature_panel_v3.parquet")
log(f"v2 panel: {panel_v2.shape}")
log(f"v3 panel: {panel_v3.shape}")

COMMON = dict(
    start="2020-01-01", end="2024-12-31",
    train_start="2014-01-01",
    rebalance_n=21, top_k=20,
    cost_bps=10, slippage_bps=5,
)

log("\nv2 backtest starting...")
t0 = time.time()
res_v2 = run_walkforward(WFParams(**COMMON), panel=panel_v2, verbose=False)
log(f"v2 done in {time.time()-t0:.0f}s — CAGR {res_v2['metrics']['cagr']*100:.2f}%")

log("\nv3 backtest starting (sector cap 25%, DD brake -15%, rank target)...")
t0 = time.time()
res_v3 = run_wf_v3(
    WFv3Params(**COMMON, sector_cap=0.25, drawdown_brake=-0.15,
               use_rank_target=True, feature_suffix="_sn"),
    panel=panel_v3, verbose=False,
)
log(f"v3 done in {time.time()-t0:.0f}s — CAGR {res_v3['metrics']['cagr']*100:.2f}%")

m2, m3 = res_v2["metrics"], res_v3["metrics"]
log("\n" + "=" * 60)
log(f"  COMPARISON: v2 vs v3 ({COMMON['start']} - {COMMON['end']})")
log("=" * 60)
rows = [
    ("CAGR (전략)",      fpct(m2.get("cagr")),         fpct(m3.get("cagr"))),
    ("CAGR (벤치)",      fpct(m2.get("bench_cagr")),   fpct(m3.get("bench_cagr"))),
    ("알파",              fpct(m2.get("alpha")),         fpct(m3.get("alpha"))),
    ("연환산 변동성",    fpct(m2.get("vol_annual")),   fpct(m3.get("vol_annual"))),
    ("Sharpe",            fnum(m2.get("sharpe")),        fnum(m3.get("sharpe"))),
    ("IR",                fnum(m2.get("info_ratio")),    fnum(m3.get("info_ratio"))),
    ("MDD",               fpct(m2.get("max_drawdown")), fpct(m3.get("max_drawdown"))),
    ("일승률",            fpct(m2.get("win_rate_daily")), fpct(m3.get("win_rate_daily"))),
    ("총수익(전략)",     fpct(m2.get("total_return")), fpct(m3.get("total_return"))),
    ("총수익(벤치)",     fpct(m2.get("bench_total_return")), fpct(m3.get("bench_total_return"))),
]
log(f'  {"지표":18s}{"v2":>12s}{"v3":>12s}')
log("  " + "-" * 42)
for label, v2, v3 in rows:
    log(f"  {label:18s}{v2:>12s}{v3:>12s}")

# Save comparison json
out = {
    "v2": {
        "metrics": res_v2["metrics"],
        "equity": [{"date": str(d.date()), "equity": float(v),
                    "benchmark": float(res_v2["benchmark_curve"].get(d, 1.0))}
                   for d, v in res_v2["equity_curve"].items()],
    },
    "v3": {
        "metrics": res_v3["metrics"],
        "equity": [{"date": str(d.date()), "equity": float(v),
                    "benchmark": float(res_v3["benchmark_curve"].get(d, 1.0))}
                   for d, v in res_v3["equity_curve"].items()],
    },
}
with open("models_store/comparison_v2_vs_v3.json", "w") as f:
    json.dump(clean(out), f)
log("\nSaved comparison_v2_vs_v3.json")
LOG.close()
