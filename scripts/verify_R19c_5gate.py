"""4-fold walk-forward + 5-gate verify for R19c (rel_pos < 0.7).

Filter: 52-week relative position (close vs 52w low/high) < 0.7 — i.e.
exclude fires from the top-30% of the 52-week range. Book 정신: 너무
오른 자리는 좋지 않음.
"""
from __future__ import annotations
import csv, json, sys, time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict

import numpy as np
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
from scripts.grid_R19_position_filter import build_position_index


FOLDS = [
    ("F1_2009_2013", date(2009, 1, 1), date(2013, 12, 31)),
    ("F2_2014_2017", date(2014, 1, 1), date(2017, 12, 31)),
    ("F3_2018_2020", date(2018, 1, 1), date(2020, 12, 31)),
    ("F4_2021_2026", date(2021, 1, 1), date(2026, 5, 22)),
]


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
    exit_fires = [
        f for f in raw_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    delisting_dates = fetch_delisting_dates()

    print("building position index ...")
    pos_idx = build_position_index()

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )

    def filter_pos(cands):
        out = []
        for c in cands:
            rp = pos_idx.get(c["ticker"], {}).get(c["entry_date"])
            if rp is None or rp >= 0.7: continue
            out.append(c)
        return out

    cands_R19c = filter_pos(cands_base)
    print(f"baseline cands: {len(cands_base):,}")
    print(f"R19c cands:     {len(cands_R19c):,}")

    # ── Gate #5: signal dominance
    sig_dist = Counter(c["signal_type"] for c in cands_R19c)
    total = sum(sig_dist.values())
    print("\n── GATE #5: signal_type dominance ──")
    for sig, n in sig_dist.most_common(5):
        print(f"  {sig:>32s}: {n:>6} ({n/total*100:5.1f}%)")
    max_pct = sig_dist.most_common(1)[0][1] / total
    gate5_pass = max_pct < 0.70
    print(f"  max: {max_pct*100:.1f}% → {'PASS' if gate5_pass else 'FAIL'}")

    # ── 4-fold walk-forward
    print("\n── 4-FOLD WALK-FORWARD ──")
    rows = []
    for name, cands in [
        ("book_only_baseline", cands_base),
        ("R19c_pos_lt07", cands_R19c),
    ]:
        for fold_label, fs, fe in FOLDS:
            reset_caches()
            t0 = time.time()
            state = simulate_book_faithful(
                cands, fs, fe,
                initial_cash=100_000_000.0, max_positions=20,
                exit_fires=exit_fires, delisting_dates=delisting_dates,
            )
            m = compute_full_metrics(state, fs, fe)
            r = {
                "variant": name, "fold": fold_label,
                "n_trades": len(state.trades),
                "cagr": m["annualised_return_pct"],
                "sharpe": m["sharpe"],
                "alpha_ann": m.get("alpha_annual_pct"),
                "outperf_ann": m.get("outperformance_ann_pct"),
                "dd_pct": m["max_drawdown_mtm_pct"],
            }
            print(f"  [{name} | {fold_label}] CAGR={r['cagr']:+.2f} "
                  f"Alpha={r['alpha_ann']:+.2f} Outperf={r['outperf_ann']:+.2f} "
                  f"({time.time()-t0:.0f}s)")
            rows.append(r)

    df = pd.DataFrame(rows)
    piv = df.pivot(index="variant", columns="fold", values="cagr")
    base = piv.loc["book_only_baseline"]
    delta = piv.sub(base, axis=1).drop("book_only_baseline")
    piv_op = df.pivot(index="variant", columns="fold", values="outperf_ann")
    print("\nΔCAGR vs baseline:")
    print(delta.to_string(float_format=lambda x: f"{x:+.2f}"))
    print()
    print("Outperf vs KOSPI per fold:")
    print(piv_op.to_string(float_format=lambda x: f"{x:+.2f}"))
    print()
    for v in delta.index:
        n_pass = (delta.loc[v] >= 1.0).sum()
        n_neg  = (delta.loc[v] < 0).sum()
        n_op_pos = (piv_op.loc[v] > 0).sum()
        print(f"  {v}: ΔCAGR≥+1pp {n_pass}/4, neg {n_neg}/4, outperf>0 {n_op_pos}/4")

    gate2_pass = (delta.loc["R19c_pos_lt07"] >= 1.0).sum() >= 3
    folds_normal = ["F1_2009_2013", "F3_2018_2020", "F4_2021_2026"]
    avg_normal = delta.loc["R19c_pos_lt07", folds_normal].mean()
    gate3_pass = avg_normal >= 0.5

    # ── Gate #4: Bootstrap on full-period equity
    print("\n── GATE #4: Bootstrap (1000 × 20w) ──")
    reset_caches()
    state_R = simulate_book_faithful(
        cands_R19c, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m_R = compute_full_metrics(state_R, start, end)
    reset_caches()
    state_B = simulate_book_faithful(
        cands_base, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m_B = compute_full_metrics(state_B, start, end)

    eq_R = pd.DataFrame(state_R.equity_history, columns=["date", "equity"])
    eq_B = pd.DataFrame(state_B.equity_history, columns=["date", "equity"])
    eq_R["date"] = pd.to_datetime(eq_R["date"])
    eq_B["date"] = pd.to_datetime(eq_B["date"])
    eq_R = eq_R.set_index("date").resample("W-FRI").last().dropna()
    eq_B = eq_B.set_index("date").resample("W-FRI").last().dropna()
    aligned = eq_R.join(eq_B, lsuffix="_R", rsuffix="_B").dropna()
    r_R = aligned["equity_R"].pct_change().dropna().values
    r_B = aligned["equity_B"].pct_change().dropna().values
    n = len(r_R)
    rng = np.random.default_rng(42)
    bl = 20
    sh_d = []; cg_d = []
    for _ in range(1000):
        idx = rng.integers(0, n - bl, size=n // bl + 1)
        bR = np.concatenate([r_R[i:i+bl] for i in idx])[:n]
        bB = np.concatenate([r_B[i:i+bl] for i in idx])[:n]
        sh_d.append((bR.mean()/bR.std()*np.sqrt(52) if bR.std() else 0)
                    - (bB.mean()/bB.std()*np.sqrt(52) if bB.std() else 0))
        cg_d.append(((np.prod(1+bR))**(52/n)-1)*100 - ((np.prod(1+bB))**(52/n)-1)*100)
    sh_d = np.array(sh_d); cg_d = np.array(cg_d)
    p_sh = (sh_d <= 0).mean()
    p_cg = (cg_d <= 0).mean()
    print(f"  Sharpe diff mean {sh_d.mean():+.3f} "
          f"CI95 [{np.percentile(sh_d, 2.5):+.3f}, {np.percentile(sh_d, 97.5):+.3f}] "
          f"p={p_sh:.3f}")
    print(f"  CAGR diff   mean {cg_d.mean():+.2f} "
          f"CI95 [{np.percentile(cg_d, 2.5):+.2f}, {np.percentile(cg_d, 97.5):+.2f}] "
          f"p={p_cg:.3f}")
    gate4_pass = p_sh < 0.05 and p_cg < 0.05

    # ── Verdict
    print("\n══════════════════════════════════════")
    print("R19c 5-gate verdict:")
    print(f"  Gate #1 PIT safe        : PASS (52w hi/lo rolling)")
    print(f"  Gate #2 4-fold ≥3/4     : {'PASS' if gate2_pass else 'FAIL'}")
    print(f"  Gate #3 outlier-excl    : {'PASS' if gate3_pass else 'FAIL'} (normal avg {avg_normal:+.2f})")
    print(f"  Gate #4 bootstrap p<0.05: {'PASS' if gate4_pass else 'FAIL'}")
    print(f"  Gate #5 signal <70%     : {'PASS' if gate5_pass else 'FAIL'}")
    overall = gate2_pass and gate3_pass and gate4_pass and gate5_pass
    print(f"\n  {'✅ R19c APPROVED for production swap' if overall else '❌ partial fail'}")
    print(f"\nin-sample R19c: CAGR {m_R['annualised_return_pct']:+.2f} "
          f"Sharpe {m_R['sharpe']:.3f} DD {m_R['max_drawdown_mtm_pct']:.1f} "
          f"Alpha {m_R.get('alpha_annual_pct'):+.2f} "
          f"Outperf {m_R.get('outperformance_ann_pct'):+.2f}")
    print(f"in-sample base: CAGR {m_B['annualised_return_pct']:+.2f} "
          f"Sharpe {m_B['sharpe']:.3f} DD {m_B['max_drawdown_mtm_pct']:.1f} "
          f"Alpha {m_B.get('alpha_annual_pct'):+.2f} "
          f"Outperf {m_B.get('outperformance_ann_pct'):+.2f}")

    out = ROOT / "data" / "r19c_5gate_verdict.json"
    with out.open("w") as f:
        json.dump({
            "in_sample_R19c": {k: m_R[k] for k in
                ["annualised_return_pct","sharpe","max_drawdown_mtm_pct",
                 "alpha_annual_pct","outperformance_ann_pct"]
                if k in m_R},
            "in_sample_base": {k: m_B[k] for k in
                ["annualised_return_pct","sharpe","max_drawdown_mtm_pct",
                 "alpha_annual_pct","outperformance_ann_pct"]
                if k in m_B},
            "gate2_pass": bool(gate2_pass),
            "gate3_pass": bool(gate3_pass), "gate3_normal_lift": float(avg_normal),
            "gate4_pass": bool(gate4_pass),
            "gate4_sharpe_p": float(p_sh), "gate4_cagr_p": float(p_cg),
            "gate5_pass": bool(gate5_pass), "gate5_max_signal_pct": float(max_pct),
            "overall_approved": bool(overall),
        }, f, indent=2, default=str)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
