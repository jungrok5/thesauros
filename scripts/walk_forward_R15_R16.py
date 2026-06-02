"""4-fold walk-forward for R15c (mom26w_pos) and R16c (body_strong_50pct).

These filters require per-bar feature lookup that doesn't fit the
generic walk_forward_4fold harness. Standalone here.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict

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
from scripts.grid_R15_R16_momentum_quality import (
    build_features, index_features, filter_cands,
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


def run_fold(cands, fs, fe, exit_fires, delisting_dates, label):
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands, fs, fe,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m = compute_full_metrics(state, fs, fe)
    return {
        "fold": label,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
        "dd_pct": m["max_drawdown_mtm_pct"],
        "seconds": time.time() - t0,
    }


def main() -> int:
    raw_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(raw_fires_all, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    LiquidityLookup()

    exit_fires = [
        f for f in raw_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    delisting_dates = fetch_delisting_dates()

    print("building features ...", flush=True)
    feat_df = build_features()
    feat_idx = index_features(feat_df)
    print(f"  indexed {len(feat_idx):,} tickers", flush=True)

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    body_pred = lambda f: f["body_strength"] is not None and f["body_strength"] > 0.5
    mom26_pred = lambda f: f["ret_26w"] is not None and f["ret_26w"] > 0
    cands_R16c = filter_cands(cands_base, feat_idx, body_pred)
    cands_R15c = filter_cands(cands_base, feat_idx, mom26_pred)
    print(f"baseline cands: {len(cands_base):,}", flush=True)
    print(f"R16c cands:     {len(cands_R16c):,}", flush=True)
    print(f"R15c cands:     {len(cands_R15c):,}", flush=True)

    rows = []
    for name, cands in [
        ("book_only_baseline", cands_base),
        ("R16c_body_strong", cands_R16c),
        ("R15c_mom26w_pos", cands_R15c),
    ]:
        for fold_label, fs, fe in FOLDS:
            print(f"\n[{name} | {fold_label}]", flush=True)
            r = run_fold(cands, fs, fe, exit_fires, delisting_dates, fold_label)
            r["variant"] = name
            print(f"  CAGR={r['cagr']:+.2f} Sharpe={r['sharpe']:.3f} "
                  f"Alpha={r['alpha_ann']:+.2f} Outperf={r['outperf_ann']:+.2f} "
                  f"trades={r['n_trades']} ({r['seconds']:.0f}s)", flush=True)
            rows.append(r)

    out = ROOT / "data" / "walk_forward_R15_R16_results.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n→ wrote {out}", flush=True)

    # Pivot ΔCAGR
    import pandas as pd
    df = pd.DataFrame(rows)
    piv = df.pivot(index="variant", columns="fold", values="cagr")
    base = piv.loc["book_only_baseline"]
    delta = piv.sub(base, axis=1).drop("book_only_baseline")
    print("\nΔCAGR vs baseline:")
    print(delta.to_string(float_format=lambda x: f"{x:+.2f}"))
    print()
    for v in delta.index:
        n_pass = (delta.loc[v] >= 1.0).sum()
        n_neg = (delta.loc[v] < 0).sum()
        print(f"  {v}: {n_pass}/4 pass, {n_neg}/4 negative")
    return 0


if __name__ == "__main__":
    sys.exit(main())
