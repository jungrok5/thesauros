"""Phase 3b: multi-factor baseline vs LightGBM vs hybrid.

지인 시스템 (Sharpe 1.2 멀티팩터) 과 직접 비교 가능한 baseline 측정.
또 우리 LightGBM 이 실제 marginal 가치 더하는지 검증.

3 modes:
  A. multifactor_only — ML 없음, deterministic 가중 rank 합
  B. lightgbm_only   — 현재 V3 baseline (5-seed 평균)
  C. hybrid         — 0.5 * LGBM + 0.5 * multifactor (둘 다 deterministic seed)

기간: 2020-2024, US S&P500 only.
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
import pandas as pd

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_3b_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L("=== Phase 3b: multi-factor vs LightGBM ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    L("\n--- Build panel (US, book features, 21d rebal) ---")
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
        use_book_features=True, book_exit_overlay=True,
    )

    # ---------------------------------------------------------------
    # A. Multi-factor ONLY (deterministic — seed 무관)
    # ---------------------------------------------------------------
    L(f"\n=== A. Multi-factor ONLY (deterministic) ===")
    t0 = time.time()
    res_mf = run_wf_v3(
        WFv3Params(**base, use_multifactor_only=True, seed=1),
        panel=panel.copy(), verbose=False,
    )
    m_mf = res_mf["metrics"]
    L(f"  Sharpe={fnum(m_mf['sharpe'])}, α={fpct(m_mf['alpha'])}, "
      f"MDD={fpct(m_mf['max_drawdown'])}, CAGR={fpct(m_mf['cagr'])}, "
      f"{time.time()-t0:.0f}s")
    # Deterministic check: 2nd run should give exact same
    res_mf2 = run_wf_v3(
        WFv3Params(**base, use_multifactor_only=True, seed=42),  # different seed
        panel=panel.copy(), verbose=False,
    )
    same = abs(res_mf['metrics']['sharpe'] - res_mf2['metrics']['sharpe']) < 1e-6
    L(f"  Determinism check (seed=1 vs seed=42): {'✅ same' if same else '❌ DIFFERENT'} "
      f"({res_mf['metrics']['sharpe']:.4f} vs {res_mf2['metrics']['sharpe']:.4f})")

    # ---------------------------------------------------------------
    # B. LightGBM ONLY (5-seed avg)
    # ---------------------------------------------------------------
    L(f"\n=== B. LightGBM ONLY (5-seed average) ===")
    seeds = [1, 7, 42, 100, 2026]
    lgbm_runs = []
    for s in seeds:
        t0 = time.time()
        res = run_wf_v3(WFv3Params(**base, seed=s),
                         panel=panel.copy(), verbose=False)
        m = res['metrics']
        lgbm_runs.append(m)
        L(f"  seed={s:>4d}: Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
          f"{time.time()-t0:.0f}s")
    sharpes_b = [r['sharpe'] for r in lgbm_runs]
    cagrs_b = [r['cagr'] for r in lgbm_runs]
    mdds_b = [r['max_drawdown'] for r in lgbm_runs]
    L(f"\n  Mean Sharpe: {np.mean(sharpes_b):+.3f} ± {np.std(sharpes_b):.3f}")
    L(f"  Mean CAGR:   {np.mean(cagrs_b)*100:+.2f}% ± {np.std(cagrs_b)*100:.2f}%")
    L(f"  Mean MDD:    {np.mean(mdds_b)*100:.2f}% ± {np.std(mdds_b)*100:.2f}%")

    # ---------------------------------------------------------------
    # C. Hybrid (50/50 LightGBM + multifactor) — 5-seed avg
    # ---------------------------------------------------------------
    L(f"\n=== C. Hybrid 50/50 (LightGBM + multifactor, 5-seed) ===")
    hybrid_runs = []
    for s in seeds:
        t0 = time.time()
        res = run_wf_v3(
            WFv3Params(**base, seed=s, use_multifactor_hybrid=True),
            panel=panel.copy(), verbose=False,
        )
        m = res['metrics']
        hybrid_runs.append(m)
        L(f"  seed={s:>4d}: Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
          f"{time.time()-t0:.0f}s")
    sharpes_c = [r['sharpe'] for r in hybrid_runs]
    cagrs_c = [r['cagr'] for r in hybrid_runs]
    L(f"\n  Mean Sharpe: {np.mean(sharpes_c):+.3f} ± {np.std(sharpes_c):.3f}")
    L(f"  Mean CAGR:   {np.mean(cagrs_c)*100:+.2f}% ± {np.std(cagrs_c)*100:.2f}%")

    # ---------------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------------
    L(f"\n{'='*72}")
    L(f"  PHASE 3b — Multi-factor vs LightGBM vs Hybrid")
    L(f"{'='*72}")
    L(f"  {'Mode':<25s} {'Sharpe':>14s} {'CAGR':>12s} {'MDD':>12s} {'Alpha':>12s}")
    L("  " + "-" * 78)
    L(f"  {'A. Multi-factor only':<25s} {fnum(m_mf['sharpe']):>14s} {fpct(m_mf['cagr']):>12s} {fpct(m_mf['max_drawdown']):>12s} {fpct(m_mf['alpha']):>12s}")
    alpha_b_mean = float(np.mean([r['alpha'] for r in lgbm_runs]))
    sharpe_b_str = f"{np.mean(sharpes_b):+.3f}±{np.std(sharpes_b):.2f}"
    L(f"  {'B. LightGBM only (avg)':<25s} {sharpe_b_str:>14s} {fpct(np.mean(cagrs_b)):>12s} {fpct(np.mean(mdds_b)):>12s} {fpct(alpha_b_mean):>12s}")
    mdd_c_mean = float(np.mean([r['max_drawdown'] for r in hybrid_runs]))
    alpha_c_mean = float(np.mean([r['alpha'] for r in hybrid_runs]))
    sharpe_c_str = f"{np.mean(sharpes_c):+.3f}±{np.std(sharpes_c):.2f}"
    L(f"  {'C. Hybrid (50/50, avg)':<25s} {sharpe_c_str:>14s} {fpct(np.mean(cagrs_c)):>12s} {fpct(mdd_c_mean):>12s} {fpct(alpha_c_mean):>12s}")

    # ---------------------------------------------------------------
    # Save
    # ---------------------------------------------------------------
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    out = {
        "phase": "3b",
        "panel_shape": list(panel.shape),
        "multifactor_only": {"metrics": clean(m_mf), "deterministic": same},
        "lightgbm_only": {
            "seeds": seeds, "runs": clean(lgbm_runs),
            "summary": {
                "sharpe_mean": float(np.mean(sharpes_b)),
                "sharpe_std": float(np.std(sharpes_b)),
                "cagr_mean": float(np.mean(cagrs_b)),
                "mdd_mean": float(np.mean(mdds_b)),
            },
        },
        "hybrid": {
            "seeds": seeds, "runs": clean(hybrid_runs),
            "summary": {
                "sharpe_mean": float(np.mean(sharpes_c)),
                "sharpe_std": float(np.std(sharpes_c)),
                "cagr_mean": float(np.mean(cagrs_c)),
            },
        },
    }
    with open(DOCS_DIR / "phase_3b_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_3b_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
