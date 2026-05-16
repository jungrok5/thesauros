"""Phase 4b: Survivorship 보정 효과 측정 (US).

가설: 현재 ML 측정이 살아있는 종목만 → bias 가능성.
   `use_survivorship_correction=True` 로 측정해서 Sharpe drop 확인.

비교:
  - Baseline (현재): MF + EXIT + LS 100/30 → Sharpe 0.572
  - + Survivorship correction: ?
"""
from __future__ import annotations

import json, math, sys, time, warnings
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
    log_path = DOCS_DIR / "phase_4b_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4b: Survivorship correction effect (US) ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Panel build ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True, with_book_features=True,
        market="us", verbose=False,
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
        use_book_features=True, book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=True, long_gross=1.0, short_gross=0.3, short_borrow_bps=50.0,
    )

    scenarios = [
        ("Baseline (no survivorship correction)", {**base, "use_survivorship_correction": False}),
        ("+ Survivorship correction", {**base, "use_survivorship_correction": True}),
    ]

    results = []
    for label, cfg in scenarios:
        L(f"\n--- {label} ---")
        t0 = time.time()
        res = run_wf_v3(WFv3Params(**cfg), panel=panel.copy(), verbose=False)
        m = res["metrics"]
        L(f"  Sharpe={m['sharpe']:+.3f}, α={m['alpha']*100:+.2f}%, "
          f"MDD={m['max_drawdown']*100:+.2f}%, CAGR={m['cagr']*100:+.2f}%, "
          f"{time.time()-t0:.0f}s")
        results.append({"label": label, "metrics": m})

    L(f"\n{'='*70}")
    L(f"  PHASE 4b — Survivorship correction effect (US)")
    L(f"{'='*70}")
    if len(results) == 2:
        s0 = results[0]['metrics']['sharpe']
        s1 = results[1]['metrics']['sharpe']
        L(f"  Sharpe drop with correction: {s1 - s0:+.3f}")
        L(f"  (negative = our baseline was over-optimistic; positive = correction helps)")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o
    with open(DOCS_DIR / "phase_4b_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({"phase": "4b", "results": results}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4b_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
