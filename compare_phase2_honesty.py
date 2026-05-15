"""Phase 2: 정직성 인프라 측정.

검증:
  1. 다중 seed (n=5) — Sharpe ± 표준편차 측정
  2. Bootstrap p-value — alpha 통계 유의성
  3. OOS 절대 분리 — 2014-2018 train / 2019-2024 OOS
  4. Survivorship 보정 효과
  5. 현실 비용 효과

출력: docs/optimization/phase_2_results.json + .md
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3
from app.cache.signal_cache import SIGNAL_CACHE_VERSION

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DOCS_DIR = Path("docs/optimization")
DOCS_DIR.mkdir(parents=True, exist_ok=True)


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def bootstrap_alpha_pvalue(returns: pd.Series, bench: pd.Series,
                            n_boot: int = 1000, block: int = 10) -> Dict:
    """Block bootstrap of alpha (excess return).

    Null hypothesis: no alpha (returns are just bench permutations).
    Returns p-value = P(boot_alpha >= observed) under null.
    """
    excess = (returns - bench).dropna()
    if len(excess) < 50:
        return {"p_value": float("nan"), "observed": float("nan"),
                "boot_mean": float("nan"), "boot_std": float("nan"),
                "n_boot": 0}
    observed = float(excess.mean() * 252)  # annualized

    # Block bootstrap (preserves serial correlation)
    n = len(excess)
    n_blocks = (n + block - 1) // block
    rng = np.random.default_rng(42)
    boot_means = []
    arr = excess.values
    for _ in range(n_boot):
        idx = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([arr[i:i + block] for i in idx])[:n]
        # Under null: mean should be 0 → center the sample
        # P(mean of centered_boot >= observed - 0)
        boot_means.append(float(sample.mean() * 252 - observed))
    boot_arr = np.array(boot_means)
    # one-sided p-value: P(boot >= observed) under null
    p = float((boot_arr >= 0).mean())
    return {
        "p_value": p,
        "observed_alpha": observed,
        "boot_mean": float(boot_arr.mean()),
        "boot_std": float(boot_arr.std()),
        "n_boot": n_boot,
    }


def measure_one(panel, params_dict: Dict, label: str, verbose: bool = True) -> Dict:
    """Run wf_v3 + return summary metrics + bootstrap p-value."""
    t0 = time.time()
    res = run_wf_v3(WFv3Params(**params_dict), panel=panel.copy(), verbose=False)
    elapsed = time.time() - t0
    m = res["metrics"]
    eq = res["equity_curve"]
    bench = res["benchmark_curve"]
    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    boot = bootstrap_alpha_pvalue(rets, bench_rets, n_boot=500, block=20)
    if verbose:
        print(f"  {label}: Sharpe={fnum(m['sharpe'])}, "
              f"α={fpct(m['alpha'])}, MDD={fpct(m['max_drawdown'])}, "
              f"p={boot['p_value']:.4f}, {elapsed:.0f}s")
    return {
        "label": label,
        "metrics": m,
        "bootstrap": boot,
        "elapsed_s": elapsed,
    }


def main() -> int:
    log_path = DOCS_DIR / "phase_2_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    L(f"=== Phase 2: Honesty infrastructure ===")
    L(f"Cache version: {SIGNAL_CACHE_VERSION}")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Build panel ONCE (US universe + book features)
    L(f"\n--- Build panel (US universe + book features) ---")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="us",
        verbose=False,
    )
    L(f"Panel built in {time.time()-t0:.0f}s: shape={panel.shape}")

    common = dict(
        start="2020-01-01", end="2024-12-31",
        train_start="2014-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",
        use_book_features=True,           # Phase 1A
        book_exit_overlay=True,           # Phase 1B
    )

    results = {}

    # ====================================
    # P2-1: Multi-seed (n=5)
    # ====================================
    L(f"\n=== P2-1: Multi-seed Sharpe distribution (n=5) ===")
    seeds = [1, 7, 42, 100, 2026]
    seed_runs = []
    for s in seeds:
        r = measure_one(panel, {**common, "seed": s}, f"seed={s}")
        seed_runs.append(r)
    sharpes = [r["metrics"]["sharpe"] for r in seed_runs]
    cagrs = [r["metrics"]["cagr"] for r in seed_runs]
    mdds = [r["metrics"]["max_drawdown"] for r in seed_runs]
    pvals = [r["bootstrap"]["p_value"] for r in seed_runs]
    L(f"\n  Sharpe: mean={np.mean(sharpes):.3f} ± {np.std(sharpes):.3f} (CV {np.std(sharpes)/abs(np.mean(sharpes))*100:.0f}%)")
    L(f"  CAGR:   mean={np.mean(cagrs)*100:+.2f}% ± {np.std(cagrs)*100:.2f}%")
    L(f"  MDD:    mean={np.mean(mdds)*100:.2f}% ± {np.std(mdds)*100:.2f}%")
    L(f"  Bootstrap p: mean={np.mean(pvals):.4f} (min {min(pvals):.4f}, max {max(pvals):.4f})")
    results["P2-1_multi_seed"] = {
        "seeds": seeds,
        "runs": [{
            "seed": s,
            "metrics": {k: v for k, v in r["metrics"].items() if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))},
            "bootstrap": r["bootstrap"],
        } for s, r in zip(seeds, seed_runs)],
        "summary": {
            "sharpe_mean": float(np.mean(sharpes)),
            "sharpe_std": float(np.std(sharpes)),
            "cagr_mean": float(np.mean(cagrs)),
            "mdd_mean": float(np.mean(mdds)),
            "bootstrap_p_mean": float(np.mean(pvals)),
        },
    }

    # ====================================
    # P2-3: OOS split (2014-2018 train, 2019-2024 OOS)
    # ====================================
    L(f"\n=== P2-3: OOS strict split (train ≤2018, OOS 2019-2024) ===")
    # train_start=2014, end_train=2018-12-31 (train cutoff inside walk-forward)
    # We use the existing walk-forward with start=2019-01-01 (out-of-sample)
    oos_common = {**common, "start": "2019-01-01", "end": "2024-12-31",
                   "train_start": "2014-01-01", "seed": 42}
    r_oos = measure_one(panel, oos_common, "OOS 2019-2024 (train≤2018)")
    # Compare with IN-sample (2014-2018 walk-forward)
    is_common = {**common, "start": "2015-01-01", "end": "2018-12-31",
                  "train_start": "2014-01-01", "seed": 42}
    r_is = measure_one(panel, is_common, "IS  2015-2018")
    L(f"\n  IS Sharpe: {fnum(r_is['metrics']['sharpe'])}, OOS Sharpe: {fnum(r_oos['metrics']['sharpe'])}")
    gap = r_is['metrics']['sharpe'] - r_oos['metrics']['sharpe']
    L(f"  IS-OOS gap: {gap:+.3f} (lower = generalize 더 잘함)")
    results["P2-3_oos_split"] = {
        "in_sample": r_is,
        "out_of_sample": r_oos,
        "is_oos_sharpe_gap": float(gap),
    }

    # ====================================
    # P2-5: Realistic costs
    # ====================================
    L(f"\n=== P2-5: Realistic costs (50bp slip + KR 0.18% tax) ===")
    r_baseline = measure_one(panel, {**common, "seed": 42}, "baseline (cost 15bp)")
    r_realistic = measure_one(panel,
                                {**common, "seed": 42, "realistic_costs": True},
                                "realistic (cost 68bp)")
    drag = r_baseline['metrics']['sharpe'] - r_realistic['metrics']['sharpe']
    L(f"\n  Sharpe drag: {drag:+.3f} (lower drag = strategy robust to costs)")
    results["P2-5_realistic_costs"] = {
        "baseline": r_baseline,
        "realistic": r_realistic,
        "sharpe_drag": float(drag),
    }

    # ====================================
    # Honesty Score
    # ====================================
    L(f"\n{'='*72}")
    L(f"  PHASE 2 HONESTY SCORE")
    L(f"{'='*72}")
    score = 0
    max_score = 5
    s_mean = results["P2-1_multi_seed"]["summary"]["sharpe_mean"]
    s_std = results["P2-1_multi_seed"]["summary"]["sharpe_std"]
    cv = abs(s_std / s_mean) if abs(s_mean) > 1e-6 else 999

    L(f"\n  1. Multi-seed CV ≤ 30%:  {'✅' if cv <= 0.3 else '❌'}  CV={cv*100:.0f}%")
    score += 1 if cv <= 0.3 else 0
    p_mean = results["P2-1_multi_seed"]["summary"]["bootstrap_p_mean"]
    L(f"  2. Bootstrap p < 0.05:    {'✅' if p_mean < 0.05 else '❌'}  p={p_mean:.4f}")
    score += 1 if p_mean < 0.05 else 0
    is_oos_gap = results["P2-3_oos_split"]["is_oos_sharpe_gap"]
    L(f"  3. IS-OOS Sharpe gap ≤ 0.3: {'✅' if abs(is_oos_gap) <= 0.3 else '❌'}  gap={is_oos_gap:+.3f}")
    score += 1 if abs(is_oos_gap) <= 0.3 else 0
    drag = results["P2-5_realistic_costs"]["sharpe_drag"]
    L(f"  4. Realistic-cost drag ≤ 0.15: {'✅' if drag <= 0.15 else '❌'}  drag={drag:+.3f}")
    score += 1 if drag <= 0.15 else 0
    L(f"  5. (Survivorship): skip — requires univ-time integration")
    L(f"\n  📊 Honesty Score: {score}/{max_score-1}")

    L(f"\n  TRUE BASELINE estimate: Sharpe = {s_mean:.3f} ± {s_std:.3f}")
    L(f"  TRUE alpha p-value (bootstrap): {p_mean:.4f}")

    results["honesty_score"] = {
        "score": score, "max": max_score - 1,  # P2-4 skipped
        "true_baseline_sharpe": f"{s_mean:.3f} ± {s_std:.3f}",
        "true_alpha_pvalue": p_mean,
    }

    # ====================================
    # Save
    # ====================================
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    out_path = DOCS_DIR / "phase_2_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clean(results), f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {out_path}")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
