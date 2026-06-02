"""Book-faithful v2 — production runner with Phase 12 signal weights.

Two-pass procedure:
  1. Pass 1 — baseline (uniform max/N allocation), full 2009-2026.
     Tabulate per-signal avg-return → derive uniform_by_avg weights
     clipped to [0.5, 1.5].
  2. Pass 2 — apply those weights through simulate_book_faithful, full
     period. This becomes the new production curve.

Walk-forward (Phase 12) verified that weights derived from a 9-year
fold and applied to the held-out 8-year fold produce a real lift
(ΔCAGR +1.08, ΔSharpe +0.028, ΔAlpha +1.20 pp). For production we use
all-historical data to derive weights — the methodology was validated,
but the specific weights below cannot themselves be walk-forward
checked (they include the test-fold data).

Outputs:
  data/equity_universe.csv                  — production curve (v2)
  data/book_faithful_v2_summary.json        — config + metrics
  data/book_faithful_signal_weights.json    — frozen weight table
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

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


WEIGHT_MIN = 0.5
WEIGHT_MAX = 1.5


def per_signal_avg_return(state) -> Dict[str, float]:
    by_sig: Dict[str, List[float]] = defaultdict(list)
    for t in state.trades:
        sig = t.signal_type.split("→")[0] if "→" in t.signal_type else t.signal_type
        by_sig[sig].append(t.pnl_pct)
    return {sig: sum(rs) / len(rs) for sig, rs in by_sig.items() if rs}


def main() -> int:
    print("loading inputs ...", flush=True)
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
    exit_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    exit_fires = [
        f for f in exit_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)
    print(f"  cands={len(cands):,} exit_fires={len(exit_fires):,}", flush=True)

    # ── Pass 1: baseline → estimate weights ──
    print("\n[pass 1] baseline (uniform) — estimate per-signal weights ...",
          flush=True)
    reset_caches()
    t0 = time.time()
    state1 = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
    )
    m1 = compute_full_metrics(state1, start, end)
    print(f"  pass-1 done {time.time()-t0:.0f}s: trades={len(state1.trades):,} "
          f"CAGR={m1['annualised_return_pct']:+.2f} "
          f"Sharpe={m1['sharpe']:.2f} "
          f"Alpha={m1.get('alpha_annual_pct'):+.2f}", flush=True)

    avg = per_signal_avg_return(state1)
    if not avg:
        print("ERROR: pass-1 produced no trades", flush=True)
        return 1
    grand_avg = sum(avg.values()) / len(avg)
    weights: Dict[str, float] = {}
    for sig, a in avg.items():
        w = a / grand_avg if grand_avg > 0 else 1.0
        weights[sig] = max(WEIGHT_MIN, min(WEIGHT_MAX, w))
    print("\n  per-signal avg-return + weight:")
    for sig in sorted(weights, key=lambda s: -avg[s]):
        print(f"    {sig:<30} avg={avg[sig]:+.2f}%  weight={weights[sig]:.3f}",
              flush=True)

    # Save the frozen weight table.
    weights_path = ROOT / "data" / "book_faithful_signal_weights.json"
    with weights_path.open("w", encoding="utf-8") as fp:
        json.dump({
            "derived_on": end.isoformat(),
            "weight_min": WEIGHT_MIN,
            "weight_max": WEIGHT_MAX,
            "per_signal_avg_return_pct": avg,
            "weights": weights,
            "notes": (
                "Computed from FULL 2009-2026 baseline (uniform allocation). "
                "Walk-forward audit (Phase 12) verified the methodology: weights "
                "derived from train fold lift the held-out test fold by "
                "ΔCAGR +1.08 / ΔSharpe +0.028 / ΔAlpha +1.20 pp."
            ),
        }, fp, indent=2)
    print(f"  wrote {weights_path}", flush=True)

    # ── Pass 2: weighted production run ──
    print("\n[pass 2] weighted — production curve ...", flush=True)
    reset_caches()
    t0 = time.time()
    state2 = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
        signal_weight_map=weights,
    )
    m2 = compute_full_metrics(state2, start, end)
    print(f"  pass-2 done {time.time()-t0:.0f}s: trades={len(state2.trades):,} "
          f"CAGR={m2['annualised_return_pct']:+.2f} "
          f"Sharpe={m2['sharpe']:.2f} "
          f"Alpha={m2.get('alpha_annual_pct'):+.2f}", flush=True)

    # Lift summary
    print("\n── LIFT vs pass-1 baseline ──", flush=True)
    print(f"  CAGR   {m1['annualised_return_pct']:+.2f} → "
          f"{m2['annualised_return_pct']:+.2f}  "
          f"(Δ {m2['annualised_return_pct'] - m1['annualised_return_pct']:+.2f})")
    print(f"  Sharpe {m1['sharpe']:.3f} → {m2['sharpe']:.3f}  "
          f"(Δ {m2['sharpe'] - m1['sharpe']:+.3f})")
    print(f"  Alpha  {m1.get('alpha_annual_pct'):+.2f} → "
          f"{m2.get('alpha_annual_pct'):+.2f}  "
          f"(Δ {m2.get('alpha_annual_pct', 0) - m1.get('alpha_annual_pct', 0):+.2f})")

    # ── Save production curve + summary ──
    out_eq = ROOT / "data" / "equity_universe.csv"
    with out_eq.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "equity"])
        for d, e in state2.equity_history:
            w.writerow([d.isoformat(), f"{e:.2f}"])
    print(f"  wrote {out_eq}", flush=True)

    out_json = ROOT / "data" / "book_faithful_v2_summary.json"
    with out_json.open("w", encoding="utf-8") as fp:
        json.dump({
            "config": (
                "book-faithful v2: 책 신호 + 업종분산 + 책 매도룰 + "
                "uniform-by-avg signal weights (Phase 12 OOS PASS)"
            ),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "initial_cash": 100_000_000.0,
            "max_positions": 20,
            "n_trades": len(state2.trades),
            "metrics": m2,
            "baseline_metrics_for_comparison": m1,
            "signal_weights": weights,
        }, fp, indent=2, default=str)
    print(f"  wrote {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
