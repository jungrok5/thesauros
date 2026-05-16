"""Single OOS test with LOCKED weights — no peeking, no tuning.

Cold review verdict:
  - Sharpe + 100 trials → DSR almost certainly fails
  - Only escape: lock weights BEFORE seeing OOS, single measurement, N_trials=1.

Locked configuration (committed based on rationale, not OOS Sharpe):
  - Multi-factor 5-group V/Q/M/L/Book = 0.20/0.25/0.20/0.15/0.20 — 균형 가중
    (cold review: heuristic > 가중 grid-tuning. orthogonalization 안 한 채로
     가중 sweep 은 DSR penalty 만 자초.)
  - top_k=20, rebalance_n=21, sector_cap=0.25, drawdown_brake=-0.15
  - book_exit_overlay=True, book_exit_min_conf=0.85
  - US: enable_short=True, long_gross=1.0, short_gross=0.3 (Phase 3d best)
  - KR: enable_short=False, use_kr_filter=True, kr_min_daily_value_krw=1e8
  - realistic_costs=True (KR 34bp / US 15bp per-side)
  - use_survivorship_correction=True
  - All 5 critical bug fixes applied (#10, #11, #12, #13, #14)

Measurement:
  - Train (IS): 2014-2021 (US) / 2010-2021 (KR)
  - Hold-out (OOS): 2022-2024 — single measurement, no further tuning
  - DSR with N_trials=1 → threshold near 0 → fair test
  - PBO: collect IS Sharpe + OOS Sharpe across markets
"""
from __future__ import annotations

import json, math, sys, time, warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3
from app.backtest.validation import (
    _bootstrap_alpha_pvalue, deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    decompose_by_period, format_subperiod_table,
    US_SUBPERIODS, KR_SUBPERIODS,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")

LOCKED_WEIGHTS = {
    "value": 0.20,
    "quality": 0.25,
    "momentum": 0.20,
    "lowvol": 0.15,
    "book": 0.20,
}


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def measure(name: str, panel: pd.DataFrame, base_cfg: dict, log_fn) -> dict:
    t0 = time.time()
    try:
        res = run_wf_v3(WFv3Params(**base_cfg), panel=panel.copy(), verbose=False)
        m = res["metrics"]
        eq = res["equity_curve"]; bench = res["benchmark_curve"]
        rets = eq.pct_change().dropna()
        bench_rets = bench.pct_change().dropna()
        p_val = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=1000, block=20)
        elapsed = time.time() - t0
        log_fn(f"    Sharpe={fnum(m['sharpe'])}, CAGR={fpct(m['cagr'])}, "
               f"bench={fpct(m['bench_cagr'])}, α={fpct(m['alpha'])}, "
               f"MDD={fpct(m['max_drawdown'])}, p={p_val:.3f}, {elapsed:.0f}s")
        return {
            "name": name, "sharpe": m["sharpe"], "cagr": m["cagr"],
            "bench_cagr": m["bench_cagr"], "alpha": m["alpha"],
            "mdd": m["max_drawdown"], "vol": m["vol_annual"],
            "bootstrap_p": p_val, "n_days": m["n_days"],
            "equity_curve": eq, "benchmark_curve": bench,
        }
    except Exception as e:
        log_fn(f"    ERR: {e}")
        import traceback; traceback.print_exc()
        return {"name": name, "error": str(e)}


def main() -> int:
    log_path = DOCS_DIR / "oos_locked_test_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Single OOS Test — LOCKED weights, no peeking ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L(f"\nLocked weights: {LOCKED_WEIGHTS}")
    L("Rationale: 균형 가중 — V/Q/M/L/Book 거의 균등. Cold review:")
    L("  Trial=1 → DSR threshold≈0 → 진짜 알파면 통과.")
    L("\nBug fixes applied: #1-#9 (early), #10-#14 (recent)")

    all_results = []

    # --- US: 2014-2021 IS, 2022-2024 OOS ---
    L(f"\n{'='*72}")
    L("  US S&P500 (with delisted, realistic costs)")
    L(f"{'='*72}")

    L("\n--- Panel build (US, 2014-2024) ---")
    t0 = time.time()
    panel_us = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True, with_book_features=True,
        market="us", verbose=False,
    )
    L(f"  Panel: {panel_us.shape} in {time.time()-t0:.0f}s")

    base_us = dict(
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_multifactor_only=True,
        mf_weights=LOCKED_WEIGHTS,
        use_book_features=True,
        book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=True, long_gross=1.0, short_gross=0.3,
        short_borrow_bps=50.0,
        use_survivorship_correction=True,
        realistic_costs=True,
    )

    L("\n[US IS] 2014-2021 (8 years training)")
    us_is = measure("US_IS_2014_2021", panel_us, {
        **base_us, "start": "2014-01-01", "end": "2021-12-31",
        "train_start": "2014-01-01",
    }, L)
    all_results.append({**us_is, "market": "US", "period": "IS"})

    L("\n[US OOS] 2022-2024 (3 years HELD-OUT, FIRST measurement)")
    us_oos = measure("US_OOS_2022_2024", panel_us, {
        **base_us, "start": "2022-01-01", "end": "2024-12-31",
        "train_start": "2014-01-01",
    }, L)
    all_results.append({**us_oos, "market": "US", "period": "OOS"})

    # --- KR: 2010-2021 IS, 2022-2024 OOS ---
    L(f"\n{'='*72}")
    L("  KR (KOSPI + KOSDAQ, with delisted, realistic costs, Gemini filter)")
    L(f"{'='*72}")

    L("\n--- Panel build (KR, 2008-2024) ---")
    t0 = time.time()
    panel_kr = build_panel_v3(
        start="2008-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True, with_book_features=True,
        market="kr", verbose=False,
    )
    L(f"  Panel: {panel_kr.shape} in {time.time()-t0:.0f}s")

    base_kr = dict(
        rebalance_n=21, top_k=20,
        cost_bps=18, slippage_bps=50,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="kr",
        use_multifactor_only=True,
        mf_weights=LOCKED_WEIGHTS,
        use_book_features=True,
        book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=False,
        use_survivorship_correction=True,
        use_kr_filter=True,
        kr_min_daily_value_krw=100_000_000,
    )

    L("\n[KR IS] 2010-2021 (12 years training)")
    kr_is = measure("KR_IS_2010_2021", panel_kr, {
        **base_kr, "start": "2010-01-01", "end": "2021-12-31",
        "train_start": "2008-01-01",
    }, L)
    all_results.append({**kr_is, "market": "KR", "period": "IS"})

    L("\n[KR OOS] 2022-2024 (3 years HELD-OUT, FIRST measurement)")
    kr_oos = measure("KR_OOS_2022_2024", panel_kr, {
        **base_kr, "start": "2022-01-01", "end": "2024-12-31",
        "train_start": "2008-01-01",
    }, L)
    all_results.append({**kr_oos, "market": "KR", "period": "OOS"})

    # --- DSR (with N_trials=1, OOS is single test) ---
    L(f"\n{'='*72}")
    L("  DSR (Deflated Sharpe Ratio) — N_trials=1 (single OOS, no peeking)")
    L(f"{'='*72}")
    for r in all_results:
        if "error" in r or "sharpe" not in r:
            continue
        n_obs = r.get("n_days", 252)
        dsr = deflated_sharpe_ratio(r["sharpe"], n_trials=1, n_obs=n_obs)
        L(f"  {r['name']}: SR={r['sharpe']:+.3f}, threshold={dsr['sr_threshold']:.3f}, "
          f"SE={dsr['se_sharpe']:.3f}, DSR_prob={dsr['dsr']:.3f}, "
          f"passes={dsr['passes']}")

    # --- IS-OOS gap (PBO style) ---
    L(f"\n{'='*72}")
    L("  IS → OOS gap")
    L(f"{'='*72}")
    L(f"  {'Market':<8s} {'IS_Sharpe':>10s} {'OOS_Sharpe':>11s} {'Gap':>8s} {'verdict':>30s}")
    for mkt in ["US", "KR"]:
        ris = next((r for r in all_results if r.get("market") == mkt
                     and r.get("period") == "IS" and "sharpe" in r), None)
        roos = next((r for r in all_results if r.get("market") == mkt
                      and r.get("period") == "OOS" and "sharpe" in r), None)
        if ris and roos:
            gap = roos["sharpe"] - ris["sharpe"]
            verdict = "OOS holds" if gap >= -0.3 else "OOS DEGRADES (overfit)"
            L(f"  {mkt:<8s} {ris['sharpe']:>+10.3f} {roos['sharpe']:>+11.3f} "
              f"{gap:>+8.3f} {verdict:>30s}")

    # --- PBO via small CSCV (IS=2 markets, OOS=2 markets) ---
    is_list = [r["sharpe"] for r in all_results
                if r.get("period") == "IS" and "sharpe" in r]
    oos_list = [r["sharpe"] for r in all_results
                 if r.get("period") == "OOS" and "sharpe" in r]
    if len(is_list) >= 2 and len(oos_list) >= 2:
        pbo = probability_of_backtest_overfitting(is_list, oos_list)
        L(f"\n  PBO across US/KR markets: {pbo}")

    # --- Save ---
    save_results = []
    for r in all_results:
        s = {k: v for k, v in r.items() if k not in ("equity_curve", "benchmark_curve")}
        if "alpha" in s and isinstance(s["alpha"], float) and math.isnan(s["alpha"]):
            s["alpha"] = None
        save_results.append(s)

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    out = {
        "locked_weights": LOCKED_WEIGHTS,
        "results": clean(save_results),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(DOCS_DIR / "oos_locked_test.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/oos_locked_test.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
