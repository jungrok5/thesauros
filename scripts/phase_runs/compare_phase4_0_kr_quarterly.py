"""Phase 4-0 variant: KR canonical with 63-day (quarterly) rebalance.

Hypothesis: cost drag +0.58 Sharpe (at 21-day rebalance) is the dominant
issue. Quarterly rebalance should cut turnover ~3x → cost drag ~0.2.

Also tries:
  - top_k 30 (slightly more diversified)
  - book_exit_overlay OFF (turnover reducer)
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
    log_path = DOCS_DIR / "phase_4_0_kr_quarterly_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4-0 (quarterly): KR canonical + 63-day rebalance ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L("\nHypothesis: cost drag +0.58 from 21-day rebalance. Quarterly should help.")

    L("\n--- Panel build (KR, 2008-2024) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2008-01-01", end="2024-12-31",
        rebalance_n=63,           # ← quarterly
        with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="kr",
        verbose=False,
    )
    L(f"  Panel: {panel.shape} in {time.time()-t0:.0f}s")

    # Variants
    variants = [
        {
            "name": "monthly_baseline (Phase 4-0 v3)",
            "rebalance_n": 21,
            "top_k": 20,
            "book_exit_overlay": True,
        },
        {
            "name": "quarterly_no_book_exit",
            "rebalance_n": 63,
            "top_k": 20,
            "book_exit_overlay": False,
        },
        {
            "name": "quarterly_with_book_exit",
            "rebalance_n": 63,
            "top_k": 20,
            "book_exit_overlay": True,
        },
        {
            "name": "quarterly_top30",
            "rebalance_n": 63,
            "top_k": 30,
            "book_exit_overlay": False,
        },
    ]

    results = []
    for v in variants:
        base = dict(
            start="2010-01-01", end="2024-12-31",
            train_start="2008-01-01",
            rebalance_n=v["rebalance_n"],
            top_k=v["top_k"],
            cost_bps=18, slippage_bps=50,
            sector_cap=0.25, drawdown_brake=-0.15,
            use_rank_target=True, feature_suffix="_sn",
            market="kr",
            use_multifactor_only=True,
            mf_weights={
                "value": 0.25, "quality": 0.25,
                "momentum": 0.15, "lowvol": 0.15,
                "book": 0.20,
            },
            use_book_features=True,
            book_exit_overlay=v["book_exit_overlay"],
            book_exit_min_conf=0.85,
            enable_short=False,
            use_survivorship_correction=True,
            use_kr_filter=True,
            kr_min_daily_value_krw=100_000_000,
        )
        L(f"\n--- Variant: {v['name']} ---")
        L(f"    rebal={v['rebalance_n']}d, top_k={v['top_k']}, "
          f"book_exit={v['book_exit_overlay']}")
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
              f"MDD={fpct(m['max_drawdown'])}, vol={fpct(m['vol_annual'])}, "
              f"p={p_val:.3f}, forced={n_forced}, {time.time()-t0:.0f}s")
            results.append({
                "name": v["name"], "rebalance_n": v["rebalance_n"],
                "top_k": v["top_k"], "book_exit": v["book_exit_overlay"],
                "sharpe": m["sharpe"], "cagr": m["cagr"],
                "mdd": m["max_drawdown"], "vol": m["vol_annual"],
                "alpha": m["alpha"], "bootstrap_p": p_val,
                "n_forced_exits": n_forced,
            })
        except Exception as e:
            L(f"    ERR: {e}")
            import traceback; traceback.print_exc(file=log)

    # Sort
    rs = sorted(results, key=lambda r: r["sharpe"], reverse=True)
    L(f"\n{'='*82}")
    L(f"  PHASE 4-0 QUARTERLY SWEEP — turnover / cost drag 진단")
    L(f"{'='*82}")
    L(f"  {'name':<35s} {'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s} {'p':>7s} {'forced':>7s}")
    for r in rs:
        L(f"  {r['name']:<35s} {r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
          f"{r['mdd']*100:>+7.2f}% {r['bootstrap_p']:>7.3f} {r['n_forced_exits']:>7d}")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    with open(DOCS_DIR / "phase_4_0_kr_quarterly.json", "w", encoding="utf-8") as f:
        json.dump(clean({"variants": rs}), f, ensure_ascii=False, indent=2,
                  default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4_0_kr_quarterly.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
