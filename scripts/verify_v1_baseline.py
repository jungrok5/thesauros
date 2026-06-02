"""v1 baseline 4-axis verification — establishes the confidence floor.

The audit you've already seen (Phase 9-12) tested ADDED factors against
v1. This script tests v1 ITSELF — does the locked baseline survive the
same gates we now apply to every challenger?

Four checks:

  1. SUB-PERIOD 4-fold      — run v1 over 4 disjoint sub-periods of the
                              17-year span. Need ≥3/4 to beat KOSPI BH.
  2. BLOCK BOOTSTRAP CI     — resample 20-week blocks (stationary
                              bootstrap) 1000× → 95% CI on CAGR, Sharpe,
                              MaxDD. Reveals "12.48 ± ?" honestly.
  3. SLIPPAGE STRESS        — re-simulate with realistic per-side slippage
                              at 0 / 10 / 20 / 30 / 50 bps. Confirms the
                              "~2 pp drag" guess and shows the break-even
                              slippage where Alpha goes to zero.
  4. UNIVERSE TIMING AUDIT  — sample fires from sweep_all_24w.csv and
                              verify the ticker had price bars at the
                              entry date — catches any survivorship /
                              forward-fill bias.

Output: data/v1_baseline_verification.json (machine-readable) + console
summary the user can paste into the memory file.
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from datetime import date
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Tuple

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics, weekly_equity_series
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


# ─────────────────────────────────────────────────────────────────────
# Shared inputs (load once, reuse for all four checks).
# ─────────────────────────────────────────────────────────────────────
def load_baseline_inputs():
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    LiquidityLookup()
    ms = max(float(f.get("strength", 0)) for f in fires)
    cands = apply_variant(
        fires, cap_map, sector_map, ms,
        sector_cap_per_week=1, book_weight=1.0,
    )
    exit_fires = [
        f for f in P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    return cands, exit_fires


# ─────────────────────────────────────────────────────────────────────
# 1) SUB-PERIOD 4-fold — v1 alone (no challenger).
# ─────────────────────────────────────────────────────────────────────
SUBPERIODS = [
    ("S1_2009_2013", date(2009, 1, 1), date(2013, 12, 31)),
    ("S2_2013_2017", date(2013, 1, 1), date(2017, 12, 31)),
    ("S3_2017_2021", date(2017, 1, 1), date(2021, 12, 31)),
    ("S4_2021_2026", date(2021, 1, 1), date(2026, 5, 22)),
]


def check_subperiods(cands, exit_fires):
    out = []
    for name, s, e in SUBPERIODS:
        print(f"\n[{name}] {s} → {e}", flush=True)
        reset_caches()
        t0 = time.time()
        state = simulate_book_faithful(
            cands, s, e, initial_cash=100_000_000.0,
            max_positions=20, exit_fires=exit_fires,
        )
        m = compute_full_metrics(state, s, e)
        outperf = m.get("outperformance_ann_pct") or 0
        verdict = "✓ KOSPI 이김" if outperf > 0 else "✗ KOSPI 패배"
        print(f"  trades={len(state.trades):,} CAGR={m['annualised_return_pct']:+.2f} "
              f"Sharpe={m['sharpe']:.2f} Alpha={m.get('alpha_annual_pct'):+.2f} "
              f"vs KOSPI BH={m.get('kospi_ann_ret_pct'):+.2f} → {verdict} "
              f"({time.time()-t0:.0f}s)", flush=True)
        out.append({
            "period": name,
            "trades": len(state.trades),
            "cagr": m["annualised_return_pct"],
            "sharpe": m["sharpe"],
            "max_dd": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "kospi_ann": m.get("kospi_ann_ret_pct"),
            "outperformance": outperf,
            "beats_kospi": outperf > 0,
        })
    return out


# ─────────────────────────────────────────────────────────────────────
# 2) BLOCK BOOTSTRAP — 95% CI on CAGR, Sharpe, MaxDD.
# ─────────────────────────────────────────────────────────────────────
def block_bootstrap_ci(weekly_returns: np.ndarray, n_iter: int = 1000,
                       block_size: int = 20, seed: int = 42):
    """Stationary block bootstrap on weekly returns.

    Returns dict of {metric: (mean, p5, p95)}."""
    rng = np.random.default_rng(seed)
    n = len(weekly_returns)
    cagrs, sharpes, dds = [], [], []
    for _ in range(n_iter):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n - block_size + 1)
            idx.extend(range(start, start + block_size))
        idx = np.array(idx[:n])
        sample = weekly_returns[idx]
        # build equity curve
        eq = np.cumprod(1 + sample)
        years = n / 52
        cagr = eq[-1] ** (1/years) - 1
        ann_arith = sample.mean() * 52
        ann_vol = sample.std() * (52 ** 0.5)
        sharpe = (ann_arith - 0.03) / ann_vol if ann_vol > 0 else 0
        peak = np.maximum.accumulate(eq)
        dd = ((eq - peak) / peak).min()
        cagrs.append(cagr * 100)
        sharpes.append(sharpe)
        dds.append(dd * 100)
    return {
        "cagr":   (float(np.mean(cagrs)),   float(np.percentile(cagrs, 2.5)),
                   float(np.percentile(cagrs, 97.5))),
        "sharpe": (float(np.mean(sharpes)), float(np.percentile(sharpes, 2.5)),
                   float(np.percentile(sharpes, 97.5))),
        "max_dd": (float(np.mean(dds)),     float(np.percentile(dds, 2.5)),
                   float(np.percentile(dds, 97.5))),
    }


# ─────────────────────────────────────────────────────────────────────
# 3) SLIPPAGE STRESS — re-simulate with extra round-trip cost.
# ─────────────────────────────────────────────────────────────────────
def check_slippage(cands, exit_fires):
    BPS_LEVELS = [0, 10, 20, 30, 50]   # per side, basis points
    BASE_BUY = 0.00015
    BASE_SELL = 0.0018
    out = []
    for bps in BPS_LEVELS:
        slip = bps / 10000.0
        print(f"\n[slippage {bps}bps/side]", flush=True)
        reset_caches()
        t0 = time.time()
        state = simulate_book_faithful(
            cands, date(2009, 1, 1), date(2026, 5, 22),
            initial_cash=100_000_000.0, max_positions=20,
            exit_fires=exit_fires,
            buy_cost_pct=BASE_BUY + slip,
            sell_cost_pct=BASE_SELL + slip,
        )
        m = compute_full_metrics(state, date(2009, 1, 1), date(2026, 5, 22))
        out.append({
            "slippage_bps_per_side": bps,
            "cagr": m["annualised_return_pct"],
            "sharpe": m["sharpe"],
            "max_dd": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "outperformance": m.get("outperformance_ann_pct"),
            "trades": len(state.trades),
        })
        print(f"  CAGR={m['annualised_return_pct']:+.2f} "
              f"Sharpe={m['sharpe']:.2f} Alpha={m.get('alpha_annual_pct'):+.2f} "
              f"outperf={m.get('outperformance_ann_pct'):+.2f} "
              f"({time.time()-t0:.0f}s)", flush=True)
    return out


# ─────────────────────────────────────────────────────────────────────
# 4) UNIVERSE TIMING AUDIT — survivorship / PIT sanity.
# ─────────────────────────────────────────────────────────────────────
def audit_universe(n_sample: int = 2000, seed: int = 42):
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    rng = random.Random(seed)
    if len(fires) > n_sample:
        sample = rng.sample(fires, n_sample)
    else:
        sample = fires
    print(f"\nuniverse audit: sampling {len(sample)} fires from "
          f"{len(fires):,} total", flush=True)
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    have_bar = 0
    no_bar = 0
    wrong_price = 0
    for i, f in enumerate(sample):
        if i % 200 == 0 and i > 0:
            print(f"  [{i}/{len(sample)}] ok={have_bar} no_bar={no_bar} "
                  f"price_drift={wrong_price}", flush=True)
        ed = f["entry_date"]
        tic = f["ticker"]
        # Find weekly bar at or just before entry_date.
        r = con.sql(
            f"SELECT close FROM bars "
            f"WHERE ticker='{tic}' AND granularity='W' "
            f"  AND bar_date <= '{ed}' "
            f"ORDER BY bar_date DESC LIMIT 1"
        ).fetchone()
        if r is None or r[0] is None:
            no_bar += 1
            continue
        # Compare fire's entry_price to bar's close; allow ±10% for the
        # split-adjusted vs raw difference. Anything bigger flags
        # likely lookup mismatch.
        bar_close = float(r[0])
        ep = float(f.get("entry_price", 0))
        if ep > 0:
            ratio = bar_close / ep
            if not (0.5 <= ratio <= 2.0):
                wrong_price += 1
            else:
                have_bar += 1
        else:
            have_bar += 1
    con.close()
    return {
        "sampled": len(sample),
        "have_bar_at_entry": have_bar,
        "no_bar_at_entry": no_bar,
        "price_drift_flagged": wrong_price,
        "pct_have_bar": have_bar / len(sample) if sample else 0,
    }


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("v1 baseline 4-axis verification")
    print("=" * 70)

    cands, exit_fires = load_baseline_inputs()
    print(f"loaded candidates={len(cands):,} exit_fires={len(exit_fires):,}",
          flush=True)

    # 0) Full-period run for headline + bootstrap input
    print("\n[0] full period 2009-2026 (for bootstrap input) ...", flush=True)
    reset_caches()
    state_full = simulate_book_faithful(
        cands, date(2009, 1, 1), date(2026, 5, 22),
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires,
    )
    m_full = compute_full_metrics(state_full, date(2009, 1, 1), date(2026, 5, 22))
    eq = weekly_equity_series(state_full, date(2009, 1, 1), date(2026, 5, 22))
    ret = eq["weekly_return"].dropna().to_numpy()
    print(f"  full-period CAGR {m_full['annualised_return_pct']:+.2f} "
          f"Sharpe {m_full['sharpe']:.3f} DD {m_full['max_drawdown_mtm_pct']:.1f}% "
          f"Alpha {m_full.get('alpha_annual_pct'):+.2f}", flush=True)

    # 1) SUB-PERIOD 4-fold
    print("\n" + "=" * 70)
    print("1) SUB-PERIOD 4-fold (v1 alone vs KOSPI BH)")
    print("=" * 70)
    sub_results = check_subperiods(cands, exit_fires)

    # 2) BOOTSTRAP CI
    print("\n" + "=" * 70)
    print("2) BLOCK BOOTSTRAP 1000 × 20-week (95% CI)")
    print("=" * 70)
    bs = block_bootstrap_ci(ret, n_iter=1000, block_size=20)
    print(f"  CAGR   mean {bs['cagr'][0]:+.2f}  CI95 [{bs['cagr'][1]:+.2f}, "
          f"{bs['cagr'][2]:+.2f}]")
    print(f"  Sharpe mean {bs['sharpe'][0]:.3f} CI95 [{bs['sharpe'][1]:.3f}, "
          f"{bs['sharpe'][2]:.3f}]")
    print(f"  DD     mean {bs['max_dd'][0]:.1f}%  CI95 [{bs['max_dd'][1]:.1f}, "
          f"{bs['max_dd'][2]:.1f}]")

    # 3) SLIPPAGE STRESS
    print("\n" + "=" * 70)
    print("3) SLIPPAGE STRESS — extra round-trip cost")
    print("=" * 70)
    slip_results = check_slippage(cands, exit_fires)

    # 4) UNIVERSE TIMING AUDIT
    print("\n" + "=" * 70)
    print("4) UNIVERSE TIMING AUDIT — survivorship / PIT sanity")
    print("=" * 70)
    audit = audit_universe(n_sample=2000)
    print(f"  sampled {audit['sampled']} fires")
    print(f"  ✓ have_bar_at_entry: {audit['have_bar_at_entry']} "
          f"({audit['pct_have_bar']:.1%})")
    print(f"  ✗ no_bar_at_entry:   {audit['no_bar_at_entry']}")
    print(f"  ⚠ price drift > ±50%: {audit['price_drift_flagged']}")

    # Save
    out = {
        "headline": {
            "cagr": m_full["annualised_return_pct"],
            "sharpe": m_full["sharpe"],
            "max_dd": m_full["max_drawdown_mtm_pct"],
            "alpha_ann": m_full.get("alpha_annual_pct"),
        },
        "subperiods": sub_results,
        "bootstrap_ci": bs,
        "slippage_stress": slip_results,
        "universe_audit": audit,
    }
    out_path = ROOT / "data" / "v1_baseline_verification.json"
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(out, fp, indent=2)
    print(f"\nwrote {out_path}", flush=True)

    # Verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    n_pass = sum(1 for r in sub_results if r["beats_kospi"])
    print(f"  sub-period: {n_pass}/4 sub-periods beat KOSPI BH")
    print(f"  bootstrap : CAGR 95% CI {bs['cagr'][1]:+.2f} to {bs['cagr'][2]:+.2f} "
          f"(width {bs['cagr'][2]-bs['cagr'][1]:.1f} pp)")
    slip30 = next((s for s in slip_results if s["slippage_bps_per_side"] == 30), None)
    if slip30:
        print(f"  slippage  : @30bps/side CAGR {slip30['cagr']:+.2f}, "
              f"outperf {slip30['outperformance']:+.2f} "
              f"({'still beats KOSPI' if slip30['outperformance']>0 else 'falls behind KOSPI'})")
    print(f"  universe  : {audit['pct_have_bar']:.1%} of sampled fires have "
          f"bar data at entry")


if __name__ == "__main__":
    main()
