"""R17 — multi-window momentum + body stack on v1.1.

R15c (26w momentum > 0) was the closest to 5-gate ≥3/4 (2/4 pass, but
all 4 folds within ±2pp — balanced distribution, no F-outlier).

R17 tests if AND-stacking momentum windows + body strength tightens
that to ≥3/4. Hypothesis: agreement across timeframes filters out
single-window noise — robust lift expected.

Variants (all on sector_cap=1 base):
  R17a  : 12w_pos AND 26w_pos              (two-window momentum agreement)
  R17b  : 4w_pos AND 26w_pos               (very-short + long)
  R17c  : 4w_pos AND 12w_pos AND 26w_pos   (all-three agreement)
  R17d  : 26w_pos AND body_strong_50pct    (R15c + R16c stack)
  R17e  : 12w_pos AND body_strong_50pct    (R15b + R16c)
  R17f  : 26w_pos + sector_cap=2           (momentum + sector relax)
  R17g  : 12w_pos AND 26w_pos AND body_50  (triple stack)
  R17h  : 26w_pos AND ret_12w > -0.05      (long-positive AND not crashing recent)

Output: data/grid_R17_results.csv
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
    print(f"  indexed: {len(feat_idx):,} tickers", flush=True)

    cands_sc1 = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    cands_sc2 = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=2, book_weight=1.0,
    )

    # Helpers
    pos = lambda key: (lambda f: f.get(key) is not None and f[key] > 0)
    gt  = lambda key, thr: (lambda f: f.get(key) is not None and f[key] > thr)
    nan_safe_and = lambda *preds: (lambda f: all(p(f) for p in preds))

    VARIANTS = [
        ("R17a_mom12_AND_26",  cands_sc1, nan_safe_and(pos("ret_12w"), pos("ret_26w"))),
        ("R17b_mom4_AND_26",   cands_sc1, nan_safe_and(pos("ret_4w"),  pos("ret_26w"))),
        ("R17c_mom_4_12_26",   cands_sc1, nan_safe_and(pos("ret_4w"),  pos("ret_12w"), pos("ret_26w"))),
        ("R17d_mom26_AND_body50",  cands_sc1, nan_safe_and(pos("ret_26w"), gt("body_strength", 0.5))),
        ("R17e_mom12_AND_body50",  cands_sc1, nan_safe_and(pos("ret_12w"), gt("body_strength", 0.5))),
        ("R17f_mom26_sec_cap2", cands_sc2, pos("ret_26w")),
        ("R17g_mom_12_26_body50", cands_sc1, nan_safe_and(pos("ret_12w"), pos("ret_26w"), gt("body_strength", 0.5))),
        ("R17h_mom26_AND_12_not_crash", cands_sc1, nan_safe_and(pos("ret_26w"), gt("ret_12w", -0.05))),
    ]

    # Baseline (sector_cap=1)
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands_sc1, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m = compute_full_metrics(state, start, end)
    print(f"\n[baseline] cands={len(cands_sc1):,} "
          f"CAGR={m['annualised_return_pct']:+.2f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f} "
          f"Outperf={m.get('outperformance_ann_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)
    out_rows = [{
        "variant": "book_only_baseline",
        "n_cands": len(cands_sc1), "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"], "sharpe": m["sharpe"],
        "dd_pct": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
    }]

    for i, (key, base_cands, pred) in enumerate(VARIANTS, start=1):
        print(f"\n[{i}/{len(VARIANTS)}] {key}", flush=True)
        cands = filter_cands(base_cands, feat_idx, pred)
        print(f"  cands: {len(cands):,}", flush=True)
        if not cands:
            continue
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
              f"trades={len(state.trades)} ({time.time()-t0:.0f}s)",
              flush=True)
        out_rows.append({
            "variant": key,
            "n_cands": len(cands), "n_trades": len(state.trades),
            "cagr": m["annualised_return_pct"], "sharpe": m["sharpe"],
            "dd_pct": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "outperf_ann": m.get("outperformance_ann_pct"),
        })

    out_path = ROOT / "data" / "grid_R17_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>30} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} trades {r['n_trades']:>5}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
