"""R1 — PIT cap_q grid on v1.1 (survivorship-corrected) universe.

Revisits the L2-style ranking (book_weight × book_signal + cap_weight ×
cap_q tent) now that the universe includes 883 delisted tickers and
the simulator auto-closes on delisted_at. Goal: see if the "5천억 peak"
intuition (mid-cap sweet spot — too small = 작전주, too big = 이미 반영)
holds up under PIT + corrected universe.

Grid:
  book_weight ∈ {0.6, 0.7, 0.8, 0.9, 1.0}
  peak_krw    ∈ {1_000억, 2_000억, 5_480억, 7_500억, 1조}
  = 5 × 5 = 25 variants, plus book-only baseline = 26.

Each variant runs simulate_book_faithful with sector_cap=1, max=20,
1억 capital, weekly exit fires, and delisting-aware exits.

Output: data/grid_R1_pit_cap_results.csv  (one row per variant)
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
    build_pit_cap_index,
)


BOOK_WEIGHTS = [0.6, 0.7, 0.8, 0.9, 1.0]
PEAKS_KRW = [
    ("1000억", 1e11),
    ("2000억", 2e11),
    ("5480억", 5.48e11),   # L2 original peak
    ("7500억", 7.5e11),
    ("1조",    1e12),
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
    LiquidityLookup()   # warm-up only

    print("building PIT cap index (delisted excluded — no shares data) ...",
          flush=True)
    pit_idx = build_pit_cap_index()

    exit_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    exit_fires = [
        f for f in exit_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    print(f"exit fires: {len(exit_fires):,}", flush=True)

    delisting_dates = fetch_delisting_dates()
    print(f"delisting map: {len(delisting_dates):,} tickers", flush=True)

    out_rows = []

    # Baseline: book-only (v1.1 production)
    print("\n[baseline] book-only sector_cap=1", flush=True)
    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"  cands: {len(cands_base):,}", flush=True)
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands_base, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m = compute_full_metrics(state, start, end)
    print(f"  CAGR={m['annualised_return_pct']:+.2f} Sharpe={m['sharpe']:.3f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f} "
          f"Outperf={m.get('outperformance_ann_pct'):+.2f} "
          f"DD={m['max_drawdown_mtm_pct']:.1f}% trades={len(state.trades)} "
          f"({time.time()-t0:.0f}s)", flush=True)
    out_rows.append({
        "variant": "book_only_baseline",
        "book_weight": 1.0, "peak_label": "n/a", "peak_krw": 0,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"], "sortino": m["sortino"],
        "calmar": m["calmar"], "dd_pct": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "kospi_ann": m.get("kospi_ann_ret_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
        "beta": m.get("beta"),
    })

    # Grid
    n_total = len(BOOK_WEIGHTS) * len(PEAKS_KRW)
    i = 0
    for bw in BOOK_WEIGHTS:
        for peak_lbl, peak_krw in PEAKS_KRW:
            i += 1
            if bw == 1.0:
                # cap_weight = 0 → peak irrelevant. Skip duplicates.
                continue
            print(f"\n[{i}/{n_total}] book_w={bw} peak={peak_lbl}", flush=True)
            cands = apply_variant(
                fires, cap_map, sector_map, max_strength,
                sector_cap_per_week=1, book_weight=bw,
                pit_cap_index=pit_idx,
                cap_peak_krw=peak_krw,
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
                "variant": f"bw{bw}_peak{peak_lbl}",
                "book_weight": bw, "peak_label": peak_lbl,
                "peak_krw": peak_krw,
                "n_trades": len(state.trades),
                "cagr": m["annualised_return_pct"],
                "sharpe": m["sharpe"], "sortino": m["sortino"],
                "calmar": m["calmar"], "dd_pct": m["max_drawdown_mtm_pct"],
                "alpha_ann": m.get("alpha_annual_pct"),
                "kospi_ann": m.get("kospi_ann_ret_pct"),
                "outperf_ann": m.get("outperformance_ann_pct"),
                "beta": m.get("beta"),
            })

    out_path = ROOT / "data" / "grid_R1_pit_cap_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path} ({len(out_rows)} rows)", flush=True)

    # Print sorted leaderboard
    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard (by alpha_ann) ──", flush=True)
    print(f"{'variant':>30} {'CAGR':>7} {'Sharpe':>7} {'DD':>6} "
          f"{'Alpha':>7} {'Outperf':>7} {'trades':>7}", flush=True)
    for r in out_rows:
        print(f"{r['variant']:>30} "
              f"{r['cagr']:+7.2f} {r['sharpe']:7.3f} "
              f"{r['dd_pct']:6.1f} {r['alpha_ann']:+7.2f} "
              f"{r['outperf_ann']:+7.2f} {r['n_trades']:>7}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
