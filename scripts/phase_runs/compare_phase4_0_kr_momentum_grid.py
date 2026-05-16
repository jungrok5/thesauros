"""Phase 4-0 momentum-heavy grid: M ∈ {.30,.35,.40,.45,.50} × B ∈ {.15,.20,.25,.30,.35}.

Previous finding: momentum-heavy (M=0.40, B=0.25) → Sharpe +0.640 in KR.
Now sweep around it to find local optimum.

Constraints:
  - Value = 0 (broken: 0% populated for KR)
  - Quality = 0.10-0.30 (working but weaker than M)
  - LowVol = 0.10-0.15 (defensive baseline)
  - Sum = 1.0
"""
from __future__ import annotations

import json, math, sys, time, warnings
from itertools import product
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3
from app.backtest.validation import (
    _bootstrap_alpha_pvalue, decompose_by_period,
    format_subperiod_table, KR_SUBPERIODS,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_4_0_kr_momentum_grid_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4-0 momentum grid: M × B sweep ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L("Prev best: M=0.40 B=0.25 → Sharpe +0.640. Now grid around it.")

    L("\n--- Panel build (KR, 2008-2024) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2008-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True, with_book_features=True,
        market="kr", verbose=False,
    )
    L(f"  Panel: {panel.shape} in {time.time()-t0:.0f}s")

    # Grid: M × B, rem split between Q (60%), L (40%)
    combos = []
    for m in (0.30, 0.35, 0.40, 0.45, 0.50):
        for b in (0.15, 0.20, 0.25, 0.30, 0.35):
            rem = 1.0 - m - b
            if rem < 0.15:  # need at least some Q+L
                continue
            q = rem * 0.60
            l = rem * 0.40
            combos.append({"value": 0.0, "quality": round(q, 3),
                            "momentum": round(m, 3), "lowvol": round(l, 3),
                            "book": round(b, 3)})

    L(f"\nGrid: {len(combos)} combos")
    results = []
    for i, w in enumerate(combos, 1):
        base = dict(
            start="2010-01-01", end="2024-12-31",
            train_start="2008-01-01",
            rebalance_n=21, top_k=20,
            cost_bps=18, slippage_bps=50,
            sector_cap=0.25, drawdown_brake=-0.15,
            use_rank_target=True, feature_suffix="_sn",
            market="kr",
            use_multifactor_only=True,
            mf_weights=w,
            use_book_features=True,
            book_exit_overlay=True, book_exit_min_conf=0.85,
            enable_short=False,
            use_survivorship_correction=True,
            use_kr_filter=True,
            kr_min_daily_value_krw=100_000_000,
        )
        t0 = time.time()
        try:
            res = run_wf_v3(WFv3Params(**base), panel=panel.copy(), verbose=False)
            m = res["metrics"]
            eq = res["equity_curve"]; bench = res["benchmark_curve"]
            rets = eq.pct_change().dropna()
            bench_rets = bench.pct_change().dropna()
            p_val = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=500, block=20)
            elapsed = time.time() - t0
            L(f"  [{i:2d}/{len(combos)}] M={w['momentum']} B={w['book']}: "
              f"Sharpe={fnum(m['sharpe'])}, CAGR={fpct(m['cagr'])}, "
              f"MDD={fpct(m['max_drawdown'])}, p={p_val:.3f}, {elapsed:.0f}s")
            results.append({
                "weights": w, "sharpe": m["sharpe"], "cagr": m["cagr"],
                "mdd": m["max_drawdown"], "vol": m["vol_annual"],
                "alpha": m["alpha"], "bootstrap_p": p_val,
                "elapsed_s": elapsed,
            })
        except Exception as e:
            L(f"  [{i}] ERR: {e}")

    rs = sorted(results, key=lambda r: r["sharpe"], reverse=True)
    L(f"\n{'='*82}")
    L(f"  PHASE 4-0 MOMENTUM GRID — Top 10 (sorted by Sharpe)")
    L(f"{'='*82}")
    L(f"  {'Rank':>4s} {'Q':>5s} {'M':>5s} {'L':>5s} {'B':>5s} {'Sharpe':>8s} "
      f"{'CAGR':>8s} {'MDD':>8s} {'p':>7s}")
    for i, r in enumerate(rs[:10], 1):
        w = r["weights"]
        L(f"  {i:>4d} {w['quality']:>5.2f} {w['momentum']:>5.2f} "
          f"{w['lowvol']:>5.2f} {w['book']:>5.2f} "
          f"{r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['mdd']*100:>+7.2f}% {r['bootstrap_p']:>7.3f}")

    best = rs[0]
    L(f"\n  Best: Q={best['weights']['quality']} M={best['weights']['momentum']} "
      f"L={best['weights']['lowvol']} B={best['weights']['book']}")
    L(f"  → Sharpe {best['sharpe']:+.3f}, p={best['bootstrap_p']:.3f}")

    # Sub-period analysis of best
    L(f"\n--- Sub-period decomposition of BEST combo ---")
    cfg_best = dict(
        start="2010-01-01", end="2024-12-31",
        train_start="2008-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=18, slippage_bps=50,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn", market="kr",
        use_multifactor_only=True, mf_weights=best["weights"],
        use_book_features=True, book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=False, use_survivorship_correction=True,
        use_kr_filter=True, kr_min_daily_value_krw=100_000_000,
    )
    res_best = run_wf_v3(WFv3Params(**cfg_best), panel=panel.copy(), verbose=False)
    eq_b = res_best["equity_curve"]; bench_b = res_best["benchmark_curve"]
    sub = decompose_by_period(eq_b, bench_b, KR_SUBPERIODS)
    L(format_subperiod_table(sub))

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_4_0_kr_momentum_grid.json", "w", encoding="utf-8") as f:
        json.dump(clean({"results": rs, "best": best, "best_sub_periods": sub}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4_0_kr_momentum_grid.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
