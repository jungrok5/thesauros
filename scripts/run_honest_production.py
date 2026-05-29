"""Honest production strategy — sector_cap=1 per ISO-week + book signal only.

Replaces scripts/run_l2_production.py (which embedded today-snapshot
cap_q with confirmed look-ahead bias — Phase 9 verification proved
PIT cap_q drops baseline CAGR from 20.65% → 8.07%).

This script writes the honest version:
  Strategy = sector_cap=1 (1 ticker per industry per ISO-week)
           + book_weight = 1.0 (no cap_q reweighting)
  Hold = 24 weeks fixed
  Max positions = 50
  No stop-loss (matches L2 winner spec)

Outputs:
  data/equity_universe.csv          — weekly equity curve (replaces L2 V0)
  data/honest_production_summary.json
  data/l2_production_summary.json   — kept for archival comparison only
                                      (not regenerated)
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


def main() -> int:
    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    cap_map = load_cap_map()    # not used (book_weight=1.0) but required by signature
    sector_map = load_sector_map()
    print(f"  sector_map: {len(sector_map):,} tickers with industry", flush=True)

    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1,
        book_weight=1.0,
    )
    print(f"  candidates after sector cap + book-only score: {len(cands):,}",
          flush=True)

    start = date(2009, 1, 1)
    end = date(2026, 5, 22)

    print("running portfolio.simulate (honest = sector_cap=1, book-only) ...",
          flush=True)
    t0 = time.time()
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0,
        max_positions=50,
        stop_loss_pct=0.0,
    )
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.0f}s : {len(state.trades):,} trades", flush=True)

    m = compute_full_metrics(state, start, end)
    print(f"\nhonest production metrics:")
    print(f"  CAGR              {m['annualised_return_pct']:+.2f}%")
    print(f"  Sharpe            {m['sharpe']:.3f}")
    print(f"  Sortino           {m['sortino']:.3f}")
    print(f"  Calmar            {m['calmar']:.3f}")
    print(f"  Max DD (MTM)      {m['max_drawdown_mtm_pct']:.2f}%")
    print(f"  Alpha annual      {m.get('alpha_annual_pct'):+.2f}%")
    print(f"  KOSPI ann ret     {m.get('kospi_ann_ret_pct'):+.2f}%")
    print(f"  Outperformance    {m.get('outperformance_ann_pct'):+.2f}%")
    print(f"  Total return      {m['total_return_pct']:+.2f}%")
    print(f"  Trades            {len(state.trades):,}")

    # Equity curve overwrites V0 baseline.
    out_eq = ROOT / "data" / "equity_universe.csv"
    print(f"\nwriting equity curve → {out_eq} ...", flush=True)
    with out_eq.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "equity"])
        for d, e in state.equity_history:
            w.writerow([d.isoformat(), f"{e:.2f}"])

    out_json = ROOT / "data" / "honest_production_summary.json"
    print(f"writing summary → {out_json} ...", flush=True)
    with out_json.open("w", encoding="utf-8") as fp:
        json.dump({
            "config": (
                "honest: sector_cap=1/ISO-week + book_weight=1.0 "
                "(cap_q removed per Phase 9 look-ahead audit); "
                "max=50, 24w hold, no SL"
            ),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "initial_cash": 10_000_000.0,
            "n_trades": len(state.trades),
            "metrics": m,
            "notes": [
                "Slippage NOT modeled — realistic CAGR ~14% (subtract ~2pp/year).",
                "Sector cap is per ISO-week, not per-holding. 24w overlapping holds "
                "may still concentrate one industry across multiple entries.",
                "Industry mapping from KOSPI-DESC + KOSDAQ-DESC (FDR), 161 categories.",
            ],
        }, fp, indent=2, default=str)

    print("done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
