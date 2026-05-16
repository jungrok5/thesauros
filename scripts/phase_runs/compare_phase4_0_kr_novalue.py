"""Phase 4-0 variant: KR with Value group ZEROED OUT.

Insight: KR Value factors (PE/PB/PS/earnings_yield) are 0% populated.
The 0.25 Value weight becomes constant 0.5 → pure noise diluting Q/M/L/B.

Test: redistribute Value weight → does removing noise help?

Weight schemes:
  - QML_book heavy:   Q=0.30, M=0.20, L=0.20, B=0.30 (Value→0)
  - book-heavy:       Q=0.20, M=0.20, L=0.15, B=0.45 (Phase 1A book validated)
  - momentum-heavy:   Q=0.20, M=0.40, L=0.15, B=0.25 (KR momentum strong)
  - quality-heavy:    Q=0.45, M=0.15, L=0.15, B=0.25 (Q has 73% coverage)
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
from app.backtest.validation import _bootstrap_alpha_pvalue

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_4_0_kr_novalue_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4-0 (no Value): KR with Value=0 redistributed ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L("\nKR Value factors all 0% non-null (PE/PB/PS/EY).")
    L("Constant 0.5 weight 25% = pure noise.")
    L("Redistribute to Q/M/L/B and see if it improves.")

    L("\n--- Panel build (KR, 2008-2024) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2008-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="kr",
        verbose=False,
    )
    L(f"  Panel: {panel.shape} in {time.time()-t0:.0f}s")

    variants = [
        ("baseline (V=0.25)",  {"value": 0.25, "quality": 0.25, "momentum": 0.15, "lowvol": 0.15, "book": 0.20}),
        ("QML_book heavy",     {"value": 0.00, "quality": 0.30, "momentum": 0.20, "lowvol": 0.20, "book": 0.30}),
        ("book-heavy",         {"value": 0.00, "quality": 0.20, "momentum": 0.20, "lowvol": 0.15, "book": 0.45}),
        ("momentum-heavy",     {"value": 0.00, "quality": 0.20, "momentum": 0.40, "lowvol": 0.15, "book": 0.25}),
        ("quality-heavy",      {"value": 0.00, "quality": 0.45, "momentum": 0.15, "lowvol": 0.15, "book": 0.25}),
        ("book-only",          {"value": 0.00, "quality": 0.00, "momentum": 0.00, "lowvol": 0.00, "book": 1.00}),
    ]

    results = []
    for name, w in variants:
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
        L(f"\n--- {name}: V={w['value']} Q={w['quality']} M={w['momentum']} L={w['lowvol']} B={w['book']} ---")
        t0 = time.time()
        try:
            res = run_wf_v3(WFv3Params(**base), panel=panel.copy(), verbose=False)
            m = res["metrics"]
            eq = res["equity_curve"]; bench = res["benchmark_curve"]
            rets = eq.pct_change().dropna()
            bench_rets = bench.pct_change().dropna()
            p_val = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=500, block=20)
            n_forced = res.get("n_forced_exits", 0)
            L(f"    Sharpe={fnum(m['sharpe'])}, CAGR={fpct(m['cagr'])}, "
              f"MDD={fpct(m['max_drawdown'])}, p={p_val:.3f}, "
              f"forced={n_forced}, {time.time()-t0:.0f}s")
            results.append({
                "name": name, "weights": w,
                "sharpe": m["sharpe"], "cagr": m["cagr"],
                "mdd": m["max_drawdown"], "vol": m["vol_annual"],
                "alpha": m["alpha"], "bootstrap_p": p_val,
                "n_forced_exits": n_forced,
            })
        except Exception as e:
            L(f"    ERR: {e}")

    rs = sorted(results, key=lambda r: r["sharpe"], reverse=True)
    L(f"\n{'='*82}")
    L(f"  PHASE 4-0 NO-VALUE SWEEP — Value 노이즈 제거 효과")
    L(f"{'='*82}")
    L(f"  {'name':<25s} {'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s} {'p':>7s}")
    for r in rs:
        L(f"  {r['name']:<25s} {r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['mdd']*100:>+7.2f}% {r['bootstrap_p']:>7.3f}")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_4_0_kr_novalue.json", "w", encoding="utf-8") as f:
        json.dump(clean({"variants": rs}), f, ensure_ascii=False, indent=2,
                  default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4_0_kr_novalue.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
