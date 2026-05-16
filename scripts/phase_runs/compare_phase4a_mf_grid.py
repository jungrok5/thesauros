"""Phase 4a: Multi-factor 가중치 grid sweep (US).

현재 default = Value 0.30 / Quality 0.30 / Momentum 0.20 / LowVol 0.20
이 진짜 최적인지 grid 로 확인.

Grid: 각 weight ∈ {0.1, 0.2, 0.3, 0.4} (총합 1.0 강제 — 81 combos 중 valid 약 20)
Train: 2014-2018, OOS: 2019-2024 (OOS 분리)
가장 OOS robust 한 가중치 → KR 측정 시 사용
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from itertools import product
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def main() -> int:
    log_path = DOCS_DIR / "phase_4a_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L("=== Phase 4a: MF weight grid sweep (US, OOS validation) ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Build panel (US, with book features) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="us",
        verbose=False,
    )
    L(f"Panel: {panel.shape} in {time.time()-t0:.0f}s")

    base = dict(
        train_start="2014-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_multifactor_only=True,
        use_book_features=True, book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=True, long_gross=1.0, short_gross=0.3, short_borrow_bps=50.0,
    )

    # Grid: 4 weights, each ∈ {0.1, 0.2, 0.3, 0.4}, sum == 1.0
    levels = [0.1, 0.2, 0.3, 0.4]
    combos = [
        (v, q, m, l)
        for v, q, m, l in product(levels, repeat=4)
        if abs(v + q + m + l - 1.0) < 1e-9
    ]
    L(f"\nGrid: {len(combos)} valid combos (sum=1.0)")

    # Measure on OOS only (2019-2024) — train ≤ 2018 baked in by walk-forward
    results = []
    for v, q, m, l in combos:
        weights = {"value": v, "quality": q, "momentum": m, "lowvol": l}
        cfg = {**base, "mf_weights": weights,
                "start": "2020-01-01", "end": "2024-12-31"}
        t0 = time.time()
        res = run_wf_v3(WFv3Params(**cfg), panel=panel.copy(), verbose=False)
        m_ = res["metrics"]
        results.append({
            "weights": weights, "sharpe": m_['sharpe'],
            "cagr": m_['cagr'], "mdd": m_['max_drawdown'],
            "alpha": m_['alpha'], "vol": m_['vol_annual'],
            "elapsed_s": time.time() - t0,
        })
        L(f"  V={v} Q={q} M={m} L={l}: Sharpe={m_['sharpe']:+.3f}, "
          f"CAGR={m_['cagr']*100:+.2f}%, MDD={m_['max_drawdown']*100:+.2f}%, "
          f"{time.time()-t0:.0f}s")

    # Sort
    results_sorted = sorted(results, key=lambda r: r['sharpe'], reverse=True)
    L(f"\n{'='*78}")
    L(f"  PHASE 4a — MF weight grid (sorted by Sharpe)")
    L(f"{'='*78}")
    L(f"  {'Rank':>4s} {'V':>4s} {'Q':>4s} {'M':>4s} {'L':>4s} {'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s}")
    for i, r in enumerate(results_sorted[:10], 1):
        w = r['weights']
        L(f"  {i:>4d} {w['value']:>4.1f} {w['quality']:>4.1f} {w['momentum']:>4.1f} {w['lowvol']:>4.1f} "
          f"{r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% {r['mdd']*100:>+7.2f}%")

    best = results_sorted[0]
    L(f"\n  Best: V={best['weights']['value']} Q={best['weights']['quality']} "
      f"M={best['weights']['momentum']} L={best['weights']['lowvol']} → "
      f"Sharpe {best['sharpe']:+.3f}")
    L(f"  Default (0.3/0.3/0.2/0.2): "
      f"Sharpe {[r['sharpe'] for r in results if r['weights']=={'value':0.3,'quality':0.3,'momentum':0.2,'lowvol':0.2}][0]:+.3f}")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_4a_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({"phase": "4a", "results": results_sorted, "best": best}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4a_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
