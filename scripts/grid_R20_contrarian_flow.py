"""R20 — contrarian flow factor.

R14 results: foreign-net-positive filter LOSES alpha → foreign buying is
LAG indicator. Reverse hypothesis: book signals work when smart money
(foreigners/institutions) haven't crowded in yet — leading-edge alpha.

Variants:
  R20a: prior_12w foreign_net ≤ 0   (스마트 머니 아직 안 들어옴)
  R20b: prior_12w foreign + inst 둘 다 ≤ 0
  R20c: R20a + R17a momentum (외국인 안 사는데 가격은 모멘텀)
  R20d: prior_12w foreign ≤ 0 AND prior_4w foreign > 0 (turn signal)
  R20e: prior_4w foreign ≤ 0 (단기 외국인 외면)
  R20f: prior_12w foreign ≤ 0 AND R19c (rel_pos < 0.7)
"""
from __future__ import annotations
import csv, sys, time
from datetime import date
from pathlib import Path
from typing import Dict

import pandas as pd
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
from scripts.grid_R14_foreign_inst_flow import build_flow_index, cum_flow
from scripts.grid_R15_R16_momentum_quality import (
    build_features, index_features, filter_cands,
)
from scripts.grid_R19_position_filter import build_position_index


def fetch_delisting_dates() -> Dict[str, date]:
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT ticker, delisted_at FROM tickers "
                    "WHERE delisted_at IS NOT NULL")
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
    exit_fires = [f for f in raw_fires_all
                  if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
                  and f.get("timeframe") == "weekly"]
    delisting_dates = fetch_delisting_dates()

    flow_idx = build_flow_index()
    feat_df = build_features()
    feat_idx = index_features(feat_df)
    pos_idx = build_position_index()

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"\nbaseline cands: {len(cands_base):,}", flush=True)

    def filter_flow_pred(cands, predicate):
        out = []
        for c in cands:
            ed = date.fromisoformat(c["entry_date"])
            f4, i4 = cum_flow(flow_idx, c["ticker"], ed, 28)
            f12, i12 = cum_flow(flow_idx, c["ticker"], ed, 84)
            if f4 is None or f12 is None: continue
            if predicate({"f4": f4, "i4": i4, "f12": f12, "i12": i12,
                          "ticker": c["ticker"], "ed": ed}):
                out.append(c)
        return out

    pos_key = lambda k: (lambda f: f.get(k) is not None and f[k] > 0)
    mom_pred = lambda f: pos_key("ret_12w")(f) and pos_key("ret_26w")(f)

    VARIANTS = [
        ("R20a_f12w_neg", lambda: filter_flow_pred(
            cands_base, lambda x: x["f12"] <= 0)),
        ("R20b_fi12w_both_neg", lambda: filter_flow_pred(
            cands_base, lambda x: x["f12"] <= 0 and (x["i12"] is None or x["i12"] <= 0))),
        ("R20c_R20a_AND_mom", lambda: filter_cands(
            filter_flow_pred(cands_base, lambda x: x["f12"] <= 0),
            feat_idx, mom_pred)),
        ("R20d_f12neg_AND_f4pos", lambda: filter_flow_pred(
            cands_base, lambda x: x["f12"] <= 0 and x["f4"] > 0)),
        ("R20e_f4w_neg", lambda: filter_flow_pred(
            cands_base, lambda x: x["f4"] <= 0)),
        ("R20f_f12neg_AND_pos_lt07", lambda: [
            c for c in filter_flow_pred(cands_base, lambda x: x["f12"] <= 0)
            if (pos_idx.get(c["ticker"], {}).get(c["entry_date"]) is not None
                and pos_idx[c["ticker"]][c["entry_date"]] < 0.7)
        ]),
    ]

    out_rows = []
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands_base, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m = compute_full_metrics(state, start, end)
    print(f"\n[baseline] CAGR={m['annualised_return_pct']:+.2f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f} "
          f"Outperf={m.get('outperformance_ann_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)
    out_rows.append({
        "variant": "book_only_baseline",
        "n_cands": len(cands_base), "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"], "sharpe": m["sharpe"],
        "dd_pct": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
    })

    for i, (key, fn) in enumerate(VARIANTS, start=1):
        print(f"\n[{i}/{len(VARIANTS)}] {key}", flush=True)
        cands = fn()
        print(f"  cands: {len(cands):,}", flush=True)
        if not cands: continue
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

    out_path = ROOT / "data" / "grid_R20_results.csv"
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
