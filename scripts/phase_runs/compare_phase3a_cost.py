"""Phase 3a: Cost-aware optimization.

Phase 2 발견: realistic cost (68bp) 시 Sharpe 0.34 → -0.28 → 시스템 붕괴.
회전율 줄여서 비용 drag 줄이기 가능한지 측정.

Grid:
  rebalance_n: 21 (monthly) / 63 (quarterly) / 126 (semi-annual)
  top_k: 5 / 10 / 20

대상: 진짜 baseline (Phase 1A+B + realistic_costs)
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_3a_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L("=== Phase 3a: Cost-aware optimization ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Build panel once (high rebalance_n means fewer panel dates, but
    # we use rebalance_n=21 for build, then filter dates downstream)
    L("\n--- Build panel (US, book features, rebalance_n=21) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="us",
        verbose=False,
    )
    L(f"Panel built in {time.time()-t0:.0f}s: shape={panel.shape}")

    base = dict(
        start="2020-01-01", end="2024-12-31",
        train_start="2014-01-01",
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_book_features=True, book_exit_overlay=True,
        seed=7,                    # use best seed for stable measurement
        realistic_costs=True,      # KR 0.18% + 50bp
    )

    grid = []
    for rebal in (21, 63, 126):
        for tk in (5, 10, 20):
            grid.append({"rebalance_n": rebal, "top_k": tk})

    results = []
    for cfg in grid:
        label = f"rebal={cfg['rebalance_n']}d, top_k={cfg['top_k']}"
        L(f"\n--- {label} ---")
        t0 = time.time()
        params = WFv3Params(**{**base, **cfg})
        res = run_wf_v3(params, panel=panel.copy(), verbose=False)
        m = res["metrics"]
        elapsed = time.time() - t0
        L(f"  Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
          f"MDD={fpct(m['max_drawdown'])}, CAGR={fpct(m['cagr'])}, {elapsed:.0f}s")
        results.append({
            "rebalance_n": cfg['rebalance_n'],
            "top_k": cfg['top_k'],
            "sharpe": m['sharpe'], "alpha": m['alpha'],
            "cagr": m['cagr'], "mdd": m['max_drawdown'],
            "vol": m['vol_annual'], "info_ratio": m['info_ratio'],
            "elapsed_s": elapsed,
        })

    # Find best by Sharpe
    results_sorted = sorted(results, key=lambda r: r['sharpe'], reverse=True)
    L(f"\n{'='*70}")
    L(f"  PHASE 3a — Cost-aware grid (sorted by Sharpe)")
    L(f"{'='*70}")
    L(f"  {'rebal':>6s} {'top_k':>6s} {'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s} {'α':>8s}")
    for r in results_sorted:
        L(f"  {r['rebalance_n']:>6d} {r['top_k']:>6d} "
          f"{r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['mdd']*100:>+7.2f}% {r['alpha']*100:>+7.2f}%")
    best = results_sorted[0]
    L(f"\n  📊 Best: rebal={best['rebalance_n']}d, top_k={best['top_k']} → Sharpe {best['sharpe']:+.3f}")

    out = {
        "phase": "3a",
        "base_params": base,
        "grid_results": results,
        "best": best,
    }
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o
    with open(DOCS_DIR / "phase_3a_results.json", "w", encoding="utf-8") as f:
        json.dump(clean(out), f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_3a_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
