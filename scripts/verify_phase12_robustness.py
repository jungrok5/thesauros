"""Phase 12 robustness audit — try multiple train/test splits.

The originally reported walk-forward used a single 60/40 split
(train 2009-2017 / test 2018-2026). To trust the lift, the same
methodology must produce consistent OOS lifts across other splits:

  Fold 1: train 2009-2014 / test 2015-2018
  Fold 2: train 2009-2017 / test 2018-2022  (original)
  Fold 3: train 2009-2020 / test 2021-2026
  Fold 4: train 2014-2019 / test 2020-2026

If lift drops or flips sign across folds → the single-fold +1.20 pp
Alpha was a sample artifact, not a stable edge. If lifts cluster
around +1 pp → real but modest edge.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


WEIGHT_MIN, WEIGHT_MAX = 0.5, 1.5


def per_signal_avg(state) -> Dict[str, float]:
    by: Dict[str, List[float]] = defaultdict(list)
    for t in state.trades:
        sig = t.signal_type.split("→")[0] if "→" in t.signal_type else t.signal_type
        by[sig].append(t.pnl_pct)
    return {s: sum(r)/len(r) for s, r in by.items() if r}


def derive_weights(state) -> Dict[str, float]:
    avg = per_signal_avg(state)
    if not avg:
        return {}
    g = sum(avg.values()) / len(avg)
    return {s: max(WEIGHT_MIN, min(WEIGHT_MAX, a/g if g > 0 else 1.0))
            for s, a in avg.items()}


def run_fold(name: str, train: Tuple[date, date], test: Tuple[date, date],
             cands, exit_fires):
    print(f"\n=== {name}: train {train[0]}→{train[1]} / "
          f"test {test[0]}→{test[1]} ===", flush=True)
    # Train baseline
    reset_caches()
    t0 = time.time()
    s_train = simulate_book_faithful(
        cands, train[0], train[1], initial_cash=100_000_000.0,
        max_positions=20, exit_fires=exit_fires,
    )
    m_train = compute_full_metrics(s_train, train[0], train[1])
    print(f"  TRAIN baseline: trades={len(s_train.trades):,} "
          f"CAGR={m_train['annualised_return_pct']:+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)
    weights = derive_weights(s_train)
    print(f"  weights: {weights}", flush=True)
    # Test baseline
    reset_caches()
    t0 = time.time()
    s_test_base = simulate_book_faithful(
        cands, test[0], test[1], initial_cash=100_000_000.0,
        max_positions=20, exit_fires=exit_fires,
    )
    m_test_base = compute_full_metrics(s_test_base, test[0], test[1])
    print(f"  TEST baseline:  CAGR={m_test_base['annualised_return_pct']:+.2f} "
          f"Sharpe={m_test_base['sharpe']:.2f} "
          f"Alpha={m_test_base.get('alpha_annual_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)
    # Test weighted
    reset_caches()
    t0 = time.time()
    s_test_w = simulate_book_faithful(
        cands, test[0], test[1], initial_cash=100_000_000.0,
        max_positions=20, exit_fires=exit_fires,
        signal_weight_map=weights,
    )
    m_test_w = compute_full_metrics(s_test_w, test[0], test[1])
    print(f"  TEST weighted:  CAGR={m_test_w['annualised_return_pct']:+.2f} "
          f"Sharpe={m_test_w['sharpe']:.2f} "
          f"Alpha={m_test_w.get('alpha_annual_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)
    dC = m_test_w["annualised_return_pct"] - m_test_base["annualised_return_pct"]
    dS = m_test_w["sharpe"] - m_test_base["sharpe"]
    dA = (m_test_w.get("alpha_annual_pct") or 0) - (m_test_base.get("alpha_annual_pct") or 0)
    print(f"  LIFT: ΔCAGR {dC:+.2f}pp  ΔSharpe {dS:+.3f}  ΔAlpha {dA:+.2f}pp",
          flush=True)
    return name, dC, dS, dA


def main():
    print("loading inputs ...", flush=True)
    fires = P.load_fires_csv(ROOT/"data/sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    cap_map = load_cap_map(); sector_map = load_sector_map()
    LiquidityLookup()
    ms = max(float(f.get("strength",0)) for f in fires)
    cands = apply_variant(fires, cap_map, sector_map, ms,
                          sector_cap_per_week=1, book_weight=1.0)
    exit_fires = [f for f in P.load_fires_csv(ROOT/"data/sweep_all_24w.csv")
                  if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
                  and f.get("timeframe") == "weekly"]
    print(f"  cands={len(cands):,} exit_fires={len(exit_fires):,}", flush=True)

    FOLDS = [
        ("F1_early",  (date(2009,1,1), date(2014,12,31)),
                      (date(2015,1,1), date(2018,12,31))),
        ("F2_original", (date(2009,1,1), date(2017,12,31)),
                        (date(2018,1,1), date(2022,12,31))),
        ("F3_late",   (date(2009,1,1), date(2020,12,31)),
                      (date(2021,1,1), date(2026,5,22))),
        ("F4_mid_slice", (date(2014,1,1), date(2019,12,31)),
                         (date(2020,1,1), date(2026,5,22))),
    ]
    results = []
    for name, tr, te in FOLDS:
        results.append(run_fold(name, tr, te, cands, exit_fires))

    print("\n=== ROBUSTNESS SUMMARY ===", flush=True)
    print(f"  {'fold':<15} {'ΔCAGR':>8} {'ΔSharpe':>9} {'ΔAlpha':>8}")
    for name, dC, dS, dA in results:
        verdict = "✓" if (dC > 0.5 or dA > 0.5) and dS > -0.02 else "✗"
        print(f"  {name:<15} {dC:>+7.2f}pp {dS:>+8.3f} {dA:>+7.2f}pp  {verdict}")
    avg_dC = sum(r[1] for r in results) / len(results)
    avg_dA = sum(r[3] for r in results) / len(results)
    n_pass = sum(1 for _, dC, dS, dA in results
                 if (dC > 0.5 or dA > 0.5) and dS > -0.02)
    print(f"\n  passes: {n_pass}/{len(results)}  avg ΔCAGR {avg_dC:+.2f}pp  "
          f"avg ΔAlpha {avg_dA:+.2f}pp")


if __name__ == "__main__":
    main()
