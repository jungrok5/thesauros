"""Walk-forward: book-faithful (no 24w / no SL) vs 24w-hold honest spec.

Train: 2009-01-01 → 2017-12-31
Test:  2018-01-01 → 2026-05-22

Two simulators compared per fold:
  A. honest 24w-hold = portfolio.simulate (book_weight=1, sector_cap=1,
                         max=50, fixed 24w SELL, no SL)
  B. book-faithful   = portfolio_book.simulate_book_faithful (same
                         buy filter, but exit on 종목별 월봉 10MA /
                         장대양봉 4등분 25% / 천장 패턴; no 24w force;
                         book engine 장대양봉 def already applied)

The CRITICAL question: does removing the (arbitrary) 24w hold lose
or keep the alpha out-of-sample? If book-faithful holds up in test,
it's the more honest production choice even though in-sample numbers
are lower.

Output: data/walk_forward_book_faithful.csv
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import (
    simulate_book_faithful, reset_caches,
)
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


FOLDS = [
    ("train", date(2009, 1, 1), date(2017, 12, 31)),
    ("test", date(2018, 1, 1), date(2026, 5, 22)),
]


def run_fold(label: str, start: date, end: date,
             max_positions: int = 20):
    print(f"\n── fold={label} ({start} → {end}) max={max_positions} ──",
          flush=True)
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()

    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )

    # ── A: 24w-hold honest baseline ────────────────────────────────
    t0 = time.time()
    state_A = P.simulate(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=50,        # honest baseline kept its max=50
        stop_loss_pct=0.0,
    )
    m_A = compute_full_metrics(state_A, start, end)
    print(f"  A (24w-hold max=50): trades={len(state_A.trades):,} "
          f"CAGR={m_A['annualised_return_pct']:+.2f} "
          f"Sharpe={m_A['sharpe']:.2f} "
          f"Alpha={m_A.get('alpha_annual_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)

    # ── B: book-faithful (no 24w force) ────────────────────────────
    exit_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    exit_fires = [
        f for f in exit_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    reset_caches()
    t0 = time.time()
    state_B = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=max_positions,
        exit_fires=exit_fires,
    )
    m_B = compute_full_metrics(state_B, start, end)
    print(f"  B (book-faithful max={max_positions}): trades={len(state_B.trades):,} "
          f"CAGR={m_B['annualised_return_pct']:+.2f} "
          f"Sharpe={m_B['sharpe']:.2f} "
          f"Alpha={m_B.get('alpha_annual_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)

    return [
        {"fold": label, "strategy": "A_24w_hold_max50",
         "n_trades": len(state_A.trades),
         **{k: m_A.get(k) for k in [
             "annualised_return_pct", "sharpe", "sortino", "calmar",
             "max_drawdown_mtm_pct", "alpha_annual_pct",
             "outperformance_ann_pct",
         ]}},
        {"fold": label, "strategy": f"B_book_faithful_max{max_positions}",
         "n_trades": len(state_B.trades),
         **{k: m_B.get(k) for k in [
             "annualised_return_pct", "sharpe", "sortino", "calmar",
             "max_drawdown_mtm_pct", "alpha_annual_pct",
             "outperformance_ann_pct",
         ]}},
    ]


def main() -> int:
    rows: List[Dict] = []
    for label, start, end in FOLDS:
        rows.extend(run_fold(label, start, end, max_positions=20))

    out = ROOT / "data" / "walk_forward_book_faithful.csv"
    with out.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote → {out}", flush=True)

    print("\n=== TEST FOLD COMPARISON ===", flush=True)
    test_rows = [r for r in rows if r["fold"] == "test"]
    for r in test_rows:
        print(f"  {r['strategy']:<30} CAGR={r['annualised_return_pct']:+.2f}  "
              f"Sharpe={r['sharpe']:.2f}  "
              f"Alpha={r['alpha_annual_pct']:+.2f}")
    # Verdict
    a = next(r for r in test_rows if r["strategy"].startswith("A_"))
    b = next(r for r in test_rows if r["strategy"].startswith("B_"))
    print(f"\nLIFT (book-faithful over 24w-hold in TEST fold):")
    print(f"  ΔCAGR   {b['annualised_return_pct'] - a['annualised_return_pct']:+.2f} pp")
    print(f"  ΔSharpe {b['sharpe'] - a['sharpe']:+.3f}")
    print(f"  ΔAlpha  {b['alpha_annual_pct'] - a['alpha_annual_pct']:+.2f} pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
