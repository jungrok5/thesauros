"""Phase 6a: V-heavy + Book group 통합 grid (Phase 4a + 5a 결합).

Phase 4a: V-heavy (V=0.4) 가 best (Sharpe 1.045) — book group 없음
Phase 5a: Book 20% 추가 시 default V=0.25 환경에서 +0.17

이 둘 결합: V-heavy 환경에서 Book 추가 시 더 높은 Sharpe?
또 selection bias 정직성 검증: 모든 combo 에 bootstrap p-value 측정.
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
from app.backtest.validation import _bootstrap_alpha_pvalue

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_6a_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 6a: V-heavy + Book group grid + Bootstrap validation ===")
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
        use_book_features=True,
        book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=True, long_gross=1.0, short_gross=0.3, short_borrow_bps=50.0,
    )

    # Build smart grid around Phase 4a best (V=0.4) + Phase 5a (Book 20%)
    # V ∈ {0.3, 0.35, 0.4}, Book ∈ {0.0, 0.1, 0.2, 0.3}
    # remainder split between Q (50%), M (30%), L (20%) by default
    combos = []
    for v in (0.30, 0.35, 0.40):
        for b in (0.00, 0.10, 0.15, 0.20, 0.25, 0.30):
            rem = 1.0 - v - b
            if rem < 0.20:  # not enough for Q+M+L
                continue
            q = rem * 0.50
            m = rem * 0.30
            l = rem * 0.20
            combos.append({"value": round(v, 3), "quality": round(q, 3),
                            "momentum": round(m, 3), "lowvol": round(l, 3),
                            "book": round(b, 3)})

    L(f"\nGrid: {len(combos)} combos (V × Book centered on Phase 4a/5a best)")

    results = []
    for i, w in enumerate(combos, 1):
        cfg = {**base, "mf_weights": w}
        t0 = time.time()
        try:
            res = run_wf_v3(WFv3Params(**cfg), panel=panel.copy(), verbose=False)
            m = res["metrics"]
            # Bootstrap p-value
            eq = res["equity_curve"]; bench = res["benchmark_curve"]
            rets = eq.pct_change().dropna()
            bench_rets = bench.pct_change().dropna()
            p_val = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=500, block=20)
            elapsed = time.time() - t0
            L(f"  [{i:2d}/{len(combos)}] V={w['value']} B={w['book']}: "
              f"Sharpe={fnum(m['sharpe'])}, CAGR={m['cagr']*100:+.2f}%, "
              f"p={p_val:.3f}, {elapsed:.0f}s")
            results.append({
                "weights": w,
                "sharpe": m['sharpe'], "cagr": m['cagr'],
                "mdd": m['max_drawdown'], "alpha": m['alpha'],
                "vol": m['vol_annual'], "bootstrap_p": p_val,
                "elapsed_s": elapsed,
            })
        except Exception as e:
            L(f"  [{i}] ERR: {e}")

    # Sort
    rs = sorted(results, key=lambda r: r['sharpe'], reverse=True)
    L(f"\n{'='*82}")
    L(f"  PHASE 6a — V-heavy + Book grid (sorted by Sharpe)")
    L(f"{'='*82}")
    L(f"  {'Rank':>4s} {'V':>5s} {'Q':>5s} {'M':>5s} {'L':>5s} {'B':>5s} "
      f"{'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s} {'p-val':>7s}")
    for i, r in enumerate(rs[:15], 1):
        w = r['weights']
        L(f"  {i:>4d} {w['value']:>5.2f} {w['quality']:>5.2f} "
          f"{w['momentum']:>5.2f} {w['lowvol']:>5.2f} {w['book']:>5.2f} "
          f"{r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['mdd']*100:>+7.2f}% {r['bootstrap_p']:>7.3f}")

    best = rs[0]
    L(f"\n  Best: V={best['weights']['value']} Q={best['weights']['quality']} "
      f"M={best['weights']['momentum']} L={best['weights']['lowvol']} "
      f"B={best['weights']['book']}")
    L(f"  → Sharpe {best['sharpe']:+.3f}, p={best['bootstrap_p']:.3f}")
    L(f"  (Phase 4a best: 1.045 V=0.4/Q=0.3/M=0.2/L=0.1/B=0)")
    L(f"  (Phase 5a default: 0.745 V=0.25/Q=0.25/M=0.15/L=0.15/B=0.2)")

    # Best with p < 0.05
    sig = [r for r in rs if r['bootstrap_p'] < 0.05]
    if sig:
        L(f"\n  Statistically significant (p<0.05): {len(sig)} combos")
        best_sig = sig[0]
        L(f"  Best significant: Sharpe {best_sig['sharpe']:+.3f}, "
          f"p={best_sig['bootstrap_p']:.3f}")
    else:
        L(f"\n  ⚠️ NO statistically significant combo (all p >= 0.05)")
        L(f"  → 모든 weight 조합의 알파가 통계적으로 무의미")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o
    with open(DOCS_DIR / "phase_6a_results.json", "w", encoding="utf-8") as f:
        json.dump(clean({"phase": "6a", "results": rs, "best": best,
                          "n_significant": len(sig)}),
                  f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_6a_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
