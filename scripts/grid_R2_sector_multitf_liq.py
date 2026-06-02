"""R2-R4 — sector_cap × multitf × liquidity single-factor grid on v1.1.

Tests three orthogonal factors on top of book-only baseline:
  R2: sector_cap_per_week ∈ {1, 2, 3, 4}   (4 variants)
  R3: multitf_bonus ∈ {0.05, 0.10, 0.15}   (3 variants)
  R4: liquidity_floor_krw ∈ {3억, 10억, 50억}  (3 variants)

Each runs simulate_book_faithful with the same v1.1 baseline (book_weight=1.0,
max=20, 1억 cap, delisting-aware exits). Variant differs only in one
apply_variant flag — so any lift can be attributed to that single factor.

Output: data/grid_R2_results.csv
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, Any

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
)


VARIANTS = [
    # sector_cap variants
    {"key": "R2_sector_cap1", "sector_cap_per_week": 1},
    {"key": "R2_sector_cap2", "sector_cap_per_week": 2},
    {"key": "R2_sector_cap3", "sector_cap_per_week": 3},
    {"key": "R2_sector_cap4", "sector_cap_per_week": 4},
    # multitf bonus (with sector_cap=1 base)
    {"key": "R3_multitf_005", "sector_cap_per_week": 1, "multitf_bonus": 0.05},
    {"key": "R3_multitf_010", "sector_cap_per_week": 1, "multitf_bonus": 0.10},
    {"key": "R3_multitf_015", "sector_cap_per_week": 1, "multitf_bonus": 0.15},
    # liquidity gate (with sector_cap=1 base)
    {"key": "R4_liq_3억",  "sector_cap_per_week": 1, "liquidity_floor_krw": 3e8},
    {"key": "R4_liq_10억", "sector_cap_per_week": 1, "liquidity_floor_krw": 1e9},
    {"key": "R4_liq_50억", "sector_cap_per_week": 1, "liquidity_floor_krw": 5e9},
]


def fetch_delisting_dates() -> Dict[str, date]:
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT ticker, delisted_at FROM tickers "
            "WHERE delisted_at IS NOT NULL"
        )
        return {t: d for t, d in cur.fetchall()}


def main() -> int:
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()

    exit_fires = [
        f for f in P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    delisting_dates = fetch_delisting_dates()
    print(f"exit fires: {len(exit_fires):,}, delisting map: {len(delisting_dates):,}",
          flush=True)

    out_rows = []
    for i, v in enumerate(VARIANTS, start=1):
        key = v.pop("key")
        print(f"\n[{i}/{len(VARIANTS)}] {key}: {v}", flush=True)
        cands = apply_variant(
            fires, cap_map, sector_map, max_strength,
            liquidity=liquidity,
            book_weight=1.0,
            **v,
        )
        print(f"  cands: {len(cands):,}", flush=True)
        reset_caches()
        t0 = time.time()
        state = simulate_book_faithful(
            cands, start, end,
            initial_cash=100_000_000.0, max_positions=20,
            exit_fires=exit_fires, delisting_dates=delisting_dates,
        )
        m = compute_full_metrics(state, start, end)
        print(f"  CAGR={m['annualised_return_pct']:+.2f} "
              f"Sharpe={m['sharpe']:.3f} "
              f"Alpha={m.get('alpha_annual_pct'):+.2f} "
              f"Outperf={m.get('outperformance_ann_pct'):+.2f} "
              f"DD={m['max_drawdown_mtm_pct']:.1f}% "
              f"trades={len(state.trades)} ({time.time()-t0:.0f}s)",
              flush=True)
        out_rows.append({
            "variant": key,
            "n_trades": len(state.trades),
            "cagr": m["annualised_return_pct"],
            "sharpe": m["sharpe"], "sortino": m["sortino"],
            "calmar": m["calmar"], "dd_pct": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "kospi_ann": m.get("kospi_ann_ret_pct"),
            "outperf_ann": m.get("outperformance_ann_pct"),
            "beta": m.get("beta"),
        })

    out_path = ROOT / "data" / "grid_R2_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard (by alpha_ann) ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>22} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} DD {r['dd_pct']:5.1f}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
