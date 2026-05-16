"""Phase 4-0 TRUTHFUL: 5 critical bug fixes 후 re-measure.

Fixed:
  #10 — DART filed_date fallback (period_end leak) — 데이터 재적재 필요한데 우선 코드만
  #11 — Training-set survivorship look-ahead
  #12 — KR shares look-ahead (revert)
  #13 — Benchmark non-rebalanced + delist NaN→0
  #14 — Embargo trading-days conversion

지난 measurements (Sharpe +0.640~+0.714) 가 위 버그들의 산물일 가능성 매우 높음.
이제 그 효과 제거 후 진짜 baseline 측정.

Configs:
  A. baseline V=0.25 (이전 Sharpe -0.605)
  B. momentum-heavy best M=0.35/B=0.30 (이전 Sharpe +0.714)
  C. book-only (이전 Sharpe +0.377)
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
    log_path = DOCS_DIR / "phase_4_0_kr_truthful_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4-0 TRUTHFUL: 5 bug fix 후 재측정 ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L("Fixes applied: #10 (DART filed_date), #11 (train survivorship),")
    L("                #12 (KR shares revert), #13 (bench rebalance + delist),")
    L("                #14 (embargo trading-days)")

    L("\n--- Panel build (KR, 2008-2024) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2008-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True, with_book_features=True,
        market="kr", verbose=False,
    )
    L(f"  Panel: {panel.shape} in {time.time()-t0:.0f}s")

    configs = [
        ("A_baseline_V25",
         {"value": 0.25, "quality": 0.25, "momentum": 0.15, "lowvol": 0.15, "book": 0.20}),
        ("B_momentum_best",
         {"value": 0.00, "quality": 0.21, "momentum": 0.35, "lowvol": 0.14, "book": 0.30}),
        ("C_book_only",
         {"value": 0.00, "quality": 0.00, "momentum": 0.00, "lowvol": 0.00, "book": 1.00}),
        ("D_momentum_heavy",
         {"value": 0.00, "quality": 0.20, "momentum": 0.40, "lowvol": 0.15, "book": 0.25}),
    ]

    results = []
    for name, w in configs:
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
        L(f"\n--- {name}: V={w['value']} Q={w['quality']} M={w['momentum']} "
          f"L={w['lowvol']} B={w['book']} ---")
        t0 = time.time()
        try:
            res = run_wf_v3(WFv3Params(**base), panel=panel.copy(), verbose=False)
            m = res["metrics"]
            eq = res["equity_curve"]; bench = res["benchmark_curve"]
            rets = eq.pct_change().dropna()
            bench_rets = bench.pct_change().dropna()
            p_val = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=1000, block=20)
            n_forced = res.get("n_forced_exits", 0)
            L(f"    Sharpe={fnum(m['sharpe'])}, CAGR={fpct(m['cagr'])}, "
              f"bench_CAGR={fpct(m['bench_cagr'])}, "
              f"α={fpct(m['alpha'])}, MDD={fpct(m['max_drawdown'])}, "
              f"p={p_val:.3f}, forced={n_forced}, {time.time()-t0:.0f}s")
            results.append({
                "name": name, "weights": w,
                "sharpe": m["sharpe"], "cagr": m["cagr"],
                "bench_cagr": m["bench_cagr"], "alpha": m["alpha"],
                "mdd": m["max_drawdown"], "vol": m["vol_annual"],
                "bootstrap_p": p_val, "n_forced_exits": n_forced,
            })
            # Sub-period for the headline (B)
            if name == "B_momentum_best":
                L(f"\n  Sub-period decomposition for {name}:")
                sub = decompose_by_period(eq, bench, KR_SUBPERIODS)
                L(format_subperiod_table(sub))
        except Exception as e:
            L(f"    ERR: {e}")
            import traceback; traceback.print_exc(file=log)

    rs = sorted(results, key=lambda r: r["sharpe"], reverse=True)
    L(f"\n{'='*82}")
    L(f"  PHASE 4-0 TRUTHFUL — 5 bug fix 후 진짜 baseline")
    L(f"{'='*82}")
    L(f"  {'name':<25s} {'Sharpe':>8s} {'CAGR':>8s} {'α':>8s} {'MDD':>8s} {'p':>7s}")
    L(f"  {'-'*82}")
    for r in rs:
        L(f"  {r['name']:<25s} {r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['alpha']*100:>+7.2f}% {r['mdd']*100:>+7.2f}% {r['bootstrap_p']:>7.3f}")

    L(f"\n  이전 (bug 있던 측정):")
    L(f"    A baseline:        Sharpe -0.605, p=0.772")
    L(f"    B momentum_best:   Sharpe +0.714, p=0.726")
    L(f"    C book_only:       Sharpe +0.377, p=0.726")
    L(f"    D momentum_heavy:  Sharpe +0.640, p=0.726")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_4_0_kr_truthful.json", "w", encoding="utf-8") as f:
        json.dump(clean({"configs": rs}), f, ensure_ascii=False, indent=2,
                  default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4_0_kr_truthful.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
