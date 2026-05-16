"""Phase 5a: Multi-factor 에 책 신호 group 추가 효과 측정.

기존 (Phase 3d): MF (V/Q/M/L 4-group) + book EXIT overlay + LS 100/30
            → Sharpe 0.572

신규 (Phase 5a): MF (V/Q/M/L/Book 5-group) + book EXIT overlay + LS 100/30
                 책 신호의 80% (ENTER/PYRAMID/WARN + trend/alignment/volume_zone)
                 도 score 에 통합 → 활용도 20% → 100%

기대:
  - Sharpe +0.05~0.15
  - Deterministic 유지
  - 책 만든 cache 의 진짜 활용
"""
from __future__ import annotations

import json, math, sys, time, warnings
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
    log_path = DOCS_DIR / "phase_5a_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 5a: MF + book group (책 신호 100% 활용) ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Panel build ---")
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
        use_book_features=True, book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=True, long_gross=1.0, short_gross=0.3, short_borrow_bps=50.0,
    )

    # Scenarios
    scenarios = [
        ("Baseline (4-group, no book)",
         {**base, "mf_weights": {"value": 0.30, "quality": 0.30,
                                    "momentum": 0.20, "lowvol": 0.20,
                                    "book": 0.0}}),
        ("+ Book group 10%",
         {**base, "mf_weights": {"value": 0.27, "quality": 0.27,
                                    "momentum": 0.18, "lowvol": 0.18,
                                    "book": 0.10}}),
        ("+ Book group 20% (default)",
         {**base, "mf_weights": {"value": 0.25, "quality": 0.25,
                                    "momentum": 0.15, "lowvol": 0.15,
                                    "book": 0.20}}),
        ("+ Book group 30%",
         {**base, "mf_weights": {"value": 0.20, "quality": 0.20,
                                    "momentum": 0.15, "lowvol": 0.15,
                                    "book": 0.30}}),
        ("Book heavy (50%)",
         {**base, "mf_weights": {"value": 0.15, "quality": 0.15,
                                    "momentum": 0.10, "lowvol": 0.10,
                                    "book": 0.50}}),
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
                "label": label, "weights": cfg["mf_weights"],
                "metrics": m, "n_forced_exits": n_forced,
            })
        except Exception as e:
            L(f"  ERR: {e}")
            import traceback; traceback.print_exc(file=log)
            results.append({"label": label, "error": str(e)})

    # ---- Summary ----
    L(f"\n{'='*88}")
    L(f"  PHASE 5a — Book group effect (책 신호 활용도 확장)")
    L(f"{'='*88}")
    L(f"  {'Scenario':<36s} {'Sharpe':>10s} {'CAGR':>10s} {'MDD':>10s} {'α':>10s}")
    L("  " + "-" * 80)
    for r in results:
        if "error" in r:
            L(f"  {r['label']:<36s} ERROR")
            continue
        m = r['metrics']
        L(f"  {r['label']:<36s} {fnum(m['sharpe']):>10s} "
          f"{fpct(m['cagr']):>10s} {fpct(m['max_drawdown']):>10s} "
          f"{fpct(m['alpha']):>10s}")

    valid = [r for r in results if "error" not in r]
    if valid:
        baseline_sharpe = valid[0]['metrics']['sharpe']
        L(f"\n  Phase 3d baseline (no book group): Sharpe {baseline_sharpe:+.3f}")
        for r in valid[1:]:
            delta = r['metrics']['sharpe'] - baseline_sharpe
            L(f"  {r['label']}: Δ {delta:+.3f}")
        best = max(valid, key=lambda r: r['metrics']['sharpe'])
        L(f"\n  📊 Best: {best['label']} → Sharpe {best['metrics']['sharpe']:+.3f}")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o
    with open(DOCS_DIR / "phase_5a_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({"phase": "5a", "results": results}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_5a_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
