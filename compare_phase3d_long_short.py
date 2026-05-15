"""Phase 3d: Long-short on multi-factor.

Baseline (3c): Multi-factor + book EXIT overlay (0.85) → Sharpe 0.462, MDD -30.8%

3d 가설: Long-short 추가 → 시장중립 → Sharpe +0.2~0.4 + MDD ↓

테스트:
  - Long-only (3c baseline)
  - LS 50/50 (gross 100% = 50% long + 50% short)
  - LS 100/100 (gross 200%, leverage)
  - LS 100/50 (long 100, short 50, partial hedge)
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
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
    log_path = DOCS_DIR / "phase_3d_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L("=== Phase 3d: Long-short on multi-factor ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Build panel ---")
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
        start="2020-01-01", end="2024-12-31",
        train_start="2014-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_multifactor_only=True,
        use_book_features=True,
        book_exit_overlay=True,
        book_exit_min_conf=0.85,    # 3c best
    )

    # ---- Scenarios ----
    scenarios = [
        ("Long-only (3c baseline)",
         {**base, "enable_short": False}),
        ("LS 50/50 (market-neutral)",
         {**base, "enable_short": True, "long_gross": 0.5, "short_gross": 0.5,
          "short_borrow_bps": 50.0}),
        ("LS 100/100 (2x leverage)",
         {**base, "enable_short": True, "long_gross": 1.0, "short_gross": 1.0,
          "short_borrow_bps": 50.0}),
        ("LS 100/50 (partial hedge)",
         {**base, "enable_short": True, "long_gross": 1.0, "short_gross": 0.5,
          "short_borrow_bps": 50.0}),
        ("LS 100/30 (mild hedge)",
         {**base, "enable_short": True, "long_gross": 1.0, "short_gross": 0.3,
          "short_borrow_bps": 50.0}),
    ]

    results = []
    for label, cfg in scenarios:
        L(f"\n--- {label} ---")
        t0 = time.time()
        try:
            res = run_wf_v3(WFv3Params(**cfg), panel=panel.copy(), verbose=False)
            m = res["metrics"]
            n_forced = res.get("n_forced_exits", 0)
            L(f"  Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
              f"MDD={fpct(m['max_drawdown'])}, CAGR={fpct(m['cagr'])}, "
              f"vol={fpct(m['vol_annual'])}, forced={n_forced}, "
              f"{time.time()-t0:.0f}s")
            results.append({
                "label": label,
                "config": {k: v for k, v in cfg.items() if k in (
                    "enable_short", "long_gross", "short_gross",
                    "short_borrow_bps", "use_multifactor_only")},
                "metrics": m,
                "n_forced_exits": n_forced,
            })
        except Exception as e:
            L(f"  ERR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc(file=log)
            results.append({"label": label, "error": str(e)})

    # ---- Summary ----
    L(f"\n{'='*84}")
    L(f"  PHASE 3d — Long-short on Multi-factor")
    L(f"{'='*84}")
    L(f"  {'Scenario':<32s} {'Sharpe':>10s} {'CAGR':>10s} {'MDD':>10s} {'Vol':>10s} {'Alpha':>10s}")
    L("  " + "-" * 88)
    for r in results:
        if "error" in r:
            L(f"  {r['label']:<32s} ERROR: {r['error']}")
            continue
        m = r['metrics']
        L(f"  {r['label']:<32s} {fnum(m['sharpe']):>10s} "
          f"{fpct(m['cagr']):>10s} {fpct(m['max_drawdown']):>10s} "
          f"{fpct(m['vol_annual']):>10s} {fpct(m['alpha']):>10s}")

    # Find best Sharpe
    valid = [r for r in results if "error" not in r]
    if valid:
        best = max(valid, key=lambda r: r['metrics']['sharpe'])
        L(f"\n  📊 Best Sharpe: {best['label']} → {fnum(best['metrics']['sharpe'])}")

    # ---- Save ----
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_3d_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({"phase": "3d", "scenarios": results}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_3d_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
