"""R18 — signal-stratified sector_cap.

Current v1.1 sector_cap=1 picks top-1 by strength per industry+week.
Result: action_strong_buy dominates (95% of candidates) because its
strength distribution sits higher than other 책 signals.

R18a: Stratify per signal_type. For each (industry, ISO-week, signal_type)
      keep top-1 by strength → up to 5 candidates per industry-week,
      one per signal. Natural balance across the 5 책 signals.

R18b: Strength quantile-normalize per signal_type so each signal's
      strength is comparable. Then standard sector_cap=1.

R18c: Hybrid — R18a + R17a momentum filter (12w_pos AND 26w_pos).

Output: data/grid_R18_results.csv
"""
from __future__ import annotations

import csv
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

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
    week_bucket,
)
from scripts.grid_R15_R16_momentum_quality import (
    build_features, index_features, filter_cands,
)


def signal_stratified_cap(
    fires: List[Dict[str, Any]],
    sector_map: Dict[str, str],
    per_signal_cap: int = 1,
    total_cap_per_week: int = 50,
) -> List[Dict[str, Any]]:
    """Top-K by strength per (industry, ISO-week, signal_type). Per-week
    overall cap prevents one industry-week from flooding the portfolio."""
    by_week: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fires:
        by_week[week_bucket(f["entry_date"])].append(f)
    out: List[Dict[str, Any]] = []
    for wk, items in by_week.items():
        items.sort(key=lambda x: float(x.get("strength", 0)), reverse=True)
        # Group by (industry, signal_type) → count seen
        kept: Dict = defaultdict(int)
        week_total = 0
        for it in items:
            sec = sector_map.get(it["ticker"], "_UNKNOWN")
            sig = it["signal_type"]
            key = (sec, sig)
            if kept[key] >= per_signal_cap:
                continue
            kept[key] += 1
            week_total += 1
            out.append(it)
            if week_total >= total_cap_per_week:
                break
    return out


def strength_quantile_normalize(
    fires: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Re-score each fire so within each signal_type, strength is mapped
    to rank-percentile (0..1). Equalises signal comparability for
    downstream sector_cap=1 ranking."""
    by_sig: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fires:
        by_sig[f["signal_type"]].append(f)
    out: List[Dict[str, Any]] = []
    for sig, group in by_sig.items():
        # Rank by strength desc
        group_sorted = sorted(group, key=lambda x: float(x.get("strength", 0)))
        n = len(group_sorted)
        for i, f in enumerate(group_sorted):
            new_f = dict(f)
            new_f["strength"] = (i + 1) / n   # rank-percentile (0..1)
            out.append(new_f)
    return out


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

    # ── R18a: signal-stratified sector_cap (per_signal_cap=1)
    cands_R18a = signal_stratified_cap(fires, sector_map,
                                       per_signal_cap=1,
                                       total_cap_per_week=50)
    # ── R18b: quantile-normalize strength then standard sector_cap=1
    fires_qn = strength_quantile_normalize(fires)
    cands_R18b = apply_variant(
        fires_qn, cap_map, sector_map, 1.0,   # normalized max_strength = 1.0
        sector_cap_per_week=1, book_weight=1.0,
    )
    # ── R18c: R18a + R17a momentum filter
    pos = lambda key: (lambda f: f.get(key) is not None and f[key] > 0)
    mom_pred = lambda f: pos("ret_12w")(f) and pos("ret_26w")(f)
    cands_R18c = filter_cands(cands_R18a, feat_idx, mom_pred)
    # ── R18d: R18b + R17a momentum filter
    cands_R18d = filter_cands(cands_R18b, feat_idx, mom_pred)

    # Baseline
    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"baseline cands:    {len(cands_base):,}", flush=True)
    print(f"R18a cands:        {len(cands_R18a):,}", flush=True)
    print(f"R18b cands:        {len(cands_R18b):,}", flush=True)
    print(f"R18c cands:        {len(cands_R18c):,}", flush=True)
    print(f"R18d cands:        {len(cands_R18d):,}", flush=True)

    out_rows = []
    for name, cands in [
        ("book_only_baseline", cands_base),
        ("R18a_signal_stratified", cands_R18a),
        ("R18b_strength_quantile", cands_R18b),
        ("R18c_R18a_AND_mom_12_26", cands_R18c),
        ("R18d_R18b_AND_mom_12_26", cands_R18d),
    ]:
        print(f"\n[{name}]", flush=True)
        # Signal dist
        from collections import Counter
        sig_dist = Counter(c["signal_type"] for c in cands)
        top_sig, top_n = sig_dist.most_common(1)[0]
        max_pct = top_n / sum(sig_dist.values()) if cands else 0
        print(f"  signal mix: {dict(sig_dist.most_common())} "
              f"(max dominance {max_pct*100:.1f}%)", flush=True)

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
            "variant": name,
            "n_cands": len(cands), "n_trades": len(state.trades),
            "cagr": m["annualised_return_pct"], "sharpe": m["sharpe"],
            "dd_pct": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "outperf_ann": m.get("outperformance_ann_pct"),
            "max_signal_pct": max_pct * 100,
        })

    out_path = ROOT / "data" / "grid_R18_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>28} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} "
              f"sig_max {r['max_signal_pct']:5.1f}% "
              f"trades {r['n_trades']:>5}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
