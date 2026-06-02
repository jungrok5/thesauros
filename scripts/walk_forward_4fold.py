"""4-fold walk-forward harness for v1.1 variant candidates.

Per project-production-change-protocol:
  Pass criterion = ≥3 of 4 folds with ΔCAGR ≥ +1.0 pp vs book-only baseline,
  AND outlier-excluded (test fold containing COVID super-cycle or AI bubble
  flagged for manual review).

Folds (test windows):
  F1: 2009-2013 (early-cycle recovery)
  F2: 2014-2017 (sideways post-Park)
  F3: 2018-2020 (COVID — outlier candidate)
  F4: 2021-2026.05 (AI bubble — outlier candidate)

Each fold's TRAIN = remainder of timeline (i.e. exclude test window).

Caller passes a list of {key, kwargs} variants. We also run book-only
baseline per fold to compute lift.

Usage:
  python scripts/walk_forward_4fold.py --variants R1_winner R2_winner
"""
from __future__ import annotations

import argparse
import csv
import json
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
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from app.db import get_conn
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
    build_pit_cap_index,
)


FOLDS = [
    ("F1_2009_2013", date(2009, 1, 1), date(2013, 12, 31)),
    ("F2_2014_2017", date(2014, 1, 1), date(2017, 12, 31)),
    ("F3_2018_2020", date(2018, 1, 1), date(2020, 12, 31)),
    ("F4_2021_2026", date(2021, 1, 1), date(2026, 5, 22)),
]


def fetch_delisting_dates() -> Dict[str, date]:
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT ticker, delisted_at FROM tickers "
            "WHERE delisted_at IS NOT NULL"
        )
        return {t: d for t, d in cur.fetchall()}


def run_one_fold(
    label: str, fold_start: date, fold_end: date,
    variant_kwargs: Dict[str, Any],
    fires, cap_map, sector_map, max_strength, liquidity, pit_idx,
    exit_fires, delisting_dates,
) -> Dict[str, Any]:
    use_pit = variant_kwargs.pop("use_pit_cap", False)
    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        liquidity=liquidity,
        pit_cap_index=(pit_idx if use_pit else None),
        **variant_kwargs,
    )
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands, fold_start, fold_end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m = compute_full_metrics(state, fold_start, fold_end)
    return {
        "fold": label,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
        "kospi_ann": m.get("kospi_ann_ret_pct"),
        "dd_pct": m["max_drawdown_mtm_pct"],
        "seconds": time.time() - t0,
    }


VARIANT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "book_only_baseline": {"sector_cap_per_week": 1, "book_weight": 1.0},
    # Placeholders filled at runtime once R1/R2 winners are known.
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=None,
                    help="variant keys to test (besides book_only_baseline)")
    ap.add_argument("--variants-json", default=None,
                    help="path to JSON dict {key: kwargs}")
    args = ap.parse_args()

    if args.variants_json:
        with open(args.variants_json) as f:
            extra = json.load(f)
        VARIANT_REGISTRY.update(extra)
    if args.variants:
        missing = [v for v in args.variants if v not in VARIANT_REGISTRY]
        if missing:
            print(f"unknown variants: {missing}", file=sys.stderr)
            return 1
        keys = ["book_only_baseline"] + args.variants
    else:
        keys = list(VARIANT_REGISTRY.keys())

    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()
    pit_idx = build_pit_cap_index()
    exit_fires = [
        f for f in P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    delisting_dates = fetch_delisting_dates()

    rows = []
    for key in keys:
        cfg = dict(VARIANT_REGISTRY[key])
        for fold_label, fs, fe in FOLDS:
            print(f"\n[{key} | {fold_label}] {cfg}", flush=True)
            cfg_clone = dict(cfg)
            r = run_one_fold(
                fold_label, fs, fe, cfg_clone,
                fires, cap_map, sector_map, max_strength,
                liquidity, pit_idx, exit_fires, delisting_dates,
            )
            r["variant"] = key
            print(f"  CAGR={r['cagr']:+.2f} Sharpe={r['sharpe']:.3f} "
                  f"Alpha={r['alpha_ann']:+.2f} Outperf={r['outperf_ann']:+.2f} "
                  f"DD={r['dd_pct']:.1f} trades={r['n_trades']} "
                  f"({r['seconds']:.0f}s)", flush=True)
            rows.append(r)

    out = ROOT / "data" / "walk_forward_4fold_results.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n→ wrote {out}", flush=True)

    # Pivot: variant × fold table of ΔCAGR vs baseline
    by_vf = {(r["variant"], r["fold"]): r for r in rows}
    print("\n── ΔCAGR vs book_only_baseline per fold ──", flush=True)
    print(f"{'variant':>30} {'F1':>7} {'F2':>7} {'F3*':>7} {'F4*':>7} "
          f"{'#pass':>6}", flush=True)
    print(f"{'  (* = potential outlier)':>30}", flush=True)
    for key in keys:
        if key == "book_only_baseline":
            continue
        deltas = []
        for fl, _, _ in FOLDS:
            base = by_vf[("book_only_baseline", fl)]["cagr"]
            var  = by_vf[(key, fl)]["cagr"]
            deltas.append(var - base)
        n_pass = sum(1 for d in deltas if d >= 1.0)
        print(f"{key:>30} "
              f"{deltas[0]:+7.2f} {deltas[1]:+7.2f} "
              f"{deltas[2]:+7.2f} {deltas[3]:+7.2f} "
              f"{n_pass:>4}/4", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
