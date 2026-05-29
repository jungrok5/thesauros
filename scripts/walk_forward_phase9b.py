"""Phase 9B walk-forward — does the peak=1000억 winner generalize?

Train: 2009-01-01 → 2017-12-31  (9 years, ~470 weeks)
Test:  2018-01-01 → 2026-05-22  (8.4 years, ~436 weeks)

Procedure:
  1. Run the full 21-variant Phase 9B grid + book-only on the train
     fold. Identify train winner by Sharpe + CAGR rank.
  2. Run the train winner + book-only + L2-default-peak-PIT on the
     test fold (out of sample).
  3. Compare lifts. If train winner's lift over book-only persists in
     test → not in-sample artifact, safe to promote to production.
     If lift collapses or flips → reject, keep book-only.

Output: data/walk_forward_phase9b.csv with fold × variant rows.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
    build_pit_cap_index, VARIANTS,
)


FOLDS = [
    ("train", date(2009, 1, 1), date(2017, 12, 31)),
    ("test", date(2018, 1, 1), date(2026, 5, 22)),
]


def run_one(
    fold_name: str, key: str, cfg: Dict[str, Any],
    fires, cap_map, sector_map, max_strength, liquidity, pit_idx,
    start: date, end: date,
) -> Dict[str, Any]:
    print(f"\n[{fold_name} | {key}] {cfg}", flush=True)
    t0 = time.time()
    raw_cfg = dict(cfg)
    use_pit = bool(raw_cfg.pop("use_pit_cap", False))
    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        liquidity=liquidity,
        pit_cap_index=(pit_idx if use_pit else None),
        **raw_cfg,
    )
    print(f"  cands: {len(cands):,}", flush=True)
    max_pos = int(raw_cfg.get("max_positions", 50))
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0,
        max_positions=max_pos,
        stop_loss_pct=0.0,
    )
    m = compute_full_metrics(state, start, end)
    print(f"  done {time.time()-t0:.0f}s: trades={len(state.trades):,} "
          f"CAGR={m['annualised_return_pct']:+.2f} Sharpe={m['sharpe']:.2f} "
          f"DD={m['max_drawdown_mtm_pct']:.1f} Alpha={m.get('alpha_annual_pct'):+.2f}",
          flush=True)
    return {
        "fold": fold_name, "variant": key,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "calmar": m["calmar"],
        "max_dd": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
    }


def main() -> int:
    print("loading fires + aux ...", flush=True)
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()
    pit_idx = build_pit_cap_index()

    # Train fold: full 21-variant Phase 9B grid + book-only control
    train_keys = sorted([k for k in VARIANTS if k.startswith("9B_")])
    train_keys.append("C_cap1_book1")     # honest baseline reference

    rows: List[Dict[str, Any]] = []
    for k in train_keys:
        rows.append(run_one(
            "train", k, VARIANTS[k],
            fires, cap_map, sector_map, max_strength, liquidity, pit_idx,
            FOLDS[0][1], FOLDS[0][2],
        ))

    # Pick train winner by Sharpe desc (tie-break CAGR desc).
    train_rows = [r for r in rows if r["fold"] == "train"
                  and r["variant"] != "C_cap1_book1"]
    train_rows.sort(key=lambda r: (-(r["sharpe"] or 0), -(r["cagr"] or 0)))
    train_winner = train_rows[0]["variant"]
    train_book_only = [r for r in rows if r["variant"] == "C_cap1_book1"][0]
    print(f"\n=== TRAIN fold complete ===", flush=True)
    print(f"Winner (by Sharpe): {train_winner}", flush=True)
    print(f"Book-only reference: Sharpe {train_book_only['sharpe']:.3f} / "
          f"CAGR {train_book_only['cagr']:+.2f}", flush=True)

    # Test fold: train winner + honest baseline + L2-default-peak PIT
    test_keys = [train_winner, "C_cap1_book1", "9B_bw080_peak5480억_PIT"]
    if "9B_bw080_peak1000억_PIT" not in test_keys:
        test_keys.append("9B_bw080_peak1000억_PIT")
    test_keys = list(dict.fromkeys(test_keys))   # dedupe, preserve order

    for k in test_keys:
        rows.append(run_one(
            "test", k, VARIANTS[k],
            fires, cap_map, sector_map, max_strength, liquidity, pit_idx,
            FOLDS[1][1], FOLDS[1][2],
        ))

    # Write summary
    out = ROOT / "data" / "walk_forward_phase9b.csv"
    with out.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "fold", "variant", "n_trades", "cagr", "sharpe",
            "calmar", "max_dd", "alpha_ann",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote → {out}", flush=True)

    # Final analysis: compare lift in test fold
    print("\n=== TEST FOLD COMPARISON ===", flush=True)
    test_book = next((r for r in rows if r["fold"] == "test"
                     and r["variant"] == "C_cap1_book1"), None)
    test_winner = next((r for r in rows if r["fold"] == "test"
                        and r["variant"] == train_winner), None)
    if test_book and test_winner:
        lift_cagr = test_winner["cagr"] - test_book["cagr"]
        lift_sharpe = test_winner["sharpe"] - test_book["sharpe"]
        lift_alpha = (test_winner["alpha_ann"] or 0) - (test_book["alpha_ann"] or 0)
        print(f"\nTEST: book-only       CAGR={test_book['cagr']:+.2f}  "
              f"Sharpe={test_book['sharpe']:.2f}  Alpha={test_book['alpha_ann']:+.2f}")
        print(f"TEST: {train_winner}  CAGR={test_winner['cagr']:+.2f}  "
              f"Sharpe={test_winner['sharpe']:.2f}  Alpha={test_winner['alpha_ann']:+.2f}")
        print(f"\nLIFT in test (winner over book-only):")
        print(f"  ΔCAGR   {lift_cagr:+.2f} pp")
        print(f"  ΔSharpe {lift_sharpe:+.3f}")
        print(f"  ΔAlpha  {lift_alpha:+.2f} pp")
        if lift_cagr > 1.0 and lift_alpha > 1.0:
            print("\n→ Winner generalizes (lift persists in test). Safe to promote.")
        elif lift_cagr < -0.5 or lift_alpha < -0.5:
            print("\n→ Winner FAILS in test (lift collapses or flips). Keep book-only.")
        else:
            print("\n→ Winner marginal in test. Decide based on Alpha/risk preference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
