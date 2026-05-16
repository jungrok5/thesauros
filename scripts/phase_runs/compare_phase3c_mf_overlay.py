"""Phase 3c: Multi-factor + book V4 EXIT overlay 측정.

3b 발견: multi-factor only = LightGBM 거의 동등 + deterministic.
3c: multi-factor 위에 책 V4 EXIT overlay 얹어서 MDD 개선 확인.

기대:
  - Sharpe 0.43 → 0.55 (Phase 1B 효과 +0.11 추정)
  - MDD -29% → -21% (-8%p 개선)
  - Deterministic 보존
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

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_3c_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L("=== Phase 3c: Multi-factor + book V4 EXIT overlay ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Build panel ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,    # for overlay
        market="us",
        verbose=False,
    )
    L(f"Panel: {panel.shape} in {time.time()-t0:.0f}s")

    base = dict(
        start="2020-01-01", end="2024-12-31",
        train_start="2014-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_multifactor_only=True,
    )

    # ---- Test scenarios ----
    scenarios = [
        ("MF only (no overlay)",
         {**base, "use_book_features": False, "book_exit_overlay": False}),
        ("MF + book EXIT overlay",
         {**base, "use_book_features": True, "book_exit_overlay": True,
          "book_exit_min_conf": 0.80}),
        ("MF + book EXIT overlay (strict 0.85)",
         {**base, "use_book_features": True, "book_exit_overlay": True,
          "book_exit_min_conf": 0.85}),
    ]

    results = []
    for label, cfg in scenarios:
        L(f"\n--- {label} ---")
        t0 = time.time()
        res = run_wf_v3(WFv3Params(**cfg), panel=panel.copy(), verbose=False)
        m = res["metrics"]
        n_forced = res.get("n_forced_exits", 0)
        L(f"  Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
          f"MDD={fpct(m['max_drawdown'])}, CAGR={fpct(m['cagr'])}, "
          f"vol={fpct(m['vol_annual'])}, forced_exits={n_forced}, "
          f"{time.time()-t0:.0f}s")
        results.append({
            "label": label,
            "config": {k: v for k, v in cfg.items() if k in (
                "use_multifactor_only", "use_book_features",
                "book_exit_overlay", "book_exit_min_conf")},
            "metrics": m,
            "n_forced_exits": n_forced,
        })

    # ---- Summary ----
    L(f"\n{'='*78}")
    L(f"  PHASE 3c — Multi-factor + book V4 EXIT overlay")
    L(f"{'='*78}")
    L(f"  {'Scenario':<40s} {'Sharpe':>10s} {'CAGR':>10s} {'MDD':>10s} {'forced':>8s}")
    L("  " + "-" * 80)
    for r in results:
        m = r['metrics']
        L(f"  {r['label']:<40s} {fnum(m['sharpe']):>10s} "
          f"{fpct(m['cagr']):>10s} {fpct(m['max_drawdown']):>10s} "
          f"{r['n_forced_exits']:>8d}")

    base_sharpe = results[0]['metrics']['sharpe']
    L(f"\n  Phase 1B (overlay) effect:")
    for r in results[1:]:
        delta = r['metrics']['sharpe'] - base_sharpe
        L(f"    {r['label']}: Sharpe Δ {delta:+.3f}")

    # ---- Save ----
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_3c_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({
            "phase": "3c",
            "scenarios": results,
        }), f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_3c_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
