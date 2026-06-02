"""R5-R10 — new exploration factors on v1.1 universe.

Past R1-R4 results showed any single factor with in-sample alpha lift
collapses to time-fold-specific outliers under 4-fold walk-forward. We
test cancellation-by-combo (R5) plus three new orthogonal factors.

  R5  : small-cap tilt + sector_cap=4 combo (R1+R2 stack)
  R8  : trend confirmation gate — entry only if ticker's monthly close
        > 10MA AND weekly close > 240MA at entry date
  R9  : multi-signal week — entry only if ≥2 distinct entry signals
        fired in the same ISO week for that ticker
  R10 : strength threshold sweep — min_strength ∈ {0.5, 0.6, 0.7}

baseline = v1.1 (book-only + sector_cap=1)

Output: data/grid_R5_R10_results.csv
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import duckdb
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
    build_pit_cap_index, week_bucket,
)


# ─────────────────────────────────────────────────────────────────────
# Trend confirmation gate (R8) — pre-build a (ticker, week_end_date) set
# where ticker's monthly close > 10MA AND weekly close > 240MA at that
# week's close.
# ─────────────────────────────────────────────────────────────────────
def build_trend_gate_index() -> set:
    """Returns set of (ticker, entry_date_iso) where both gates pass."""
    t0 = time.time()
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    weekly = con.sql(
        "SELECT ticker, bar_date, close FROM bars "
        "WHERE granularity='W' AND close IS NOT NULL ORDER BY ticker, bar_date"
    ).fetchall()
    monthly = con.sql(
        "SELECT ticker, bar_date, close FROM bars "
        "WHERE granularity='M' AND close IS NOT NULL ORDER BY ticker, bar_date"
    ).fetchall()
    con.close()

    # Per-ticker weekly: compute 240w MA; per-ticker monthly: 10M MA.
    weekly_df = pd.DataFrame(weekly, columns=["ticker", "bar_date", "close"])
    monthly_df = pd.DataFrame(monthly, columns=["ticker", "bar_date", "close"])

    weekly_df["ma240"] = (
        weekly_df.groupby("ticker")["close"]
        .transform(lambda s: s.rolling(240, min_periods=240).mean())
    )
    monthly_df["ma10"] = (
        monthly_df.groupby("ticker")["close"]
        .transform(lambda s: s.rolling(10, min_periods=10).mean())
    )

    # Build per-ticker monthly state: most-recent monthly close vs ma10
    # at any given date. Convert to sorted lookup tables.
    monthly_above: Dict[str, List[tuple]] = {}
    for tic, grp in monthly_df.groupby("ticker"):
        rows = [(r.bar_date, r.close > r.ma10 if pd.notna(r.ma10) else False)
                for r in grp.itertuples()]
        rows.sort()
        monthly_above[tic] = rows

    def monthly_above_at(ticker, d):
        rows = monthly_above.get(ticker, [])
        if not rows: return False
        # Binary search rightmost bar_date <= d
        lo, hi = 0, len(rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if rows[mid][0] <= d: lo = mid + 1
            else: hi = mid
        if lo == 0: return False
        return rows[lo-1][1]

    # Weekly: directly check at each weekly bar
    gate_ok: set = set()
    for r in weekly_df.itertuples():
        if pd.isna(r.ma240): continue
        if r.close <= r.ma240: continue
        if not monthly_above_at(r.ticker, r.bar_date): continue
        gate_ok.add((r.ticker, r.bar_date.isoformat()))
    print(f"  trend gate: {len(gate_ok):,} (ticker,date) pairs pass "
          f"in {time.time()-t0:.1f}s", flush=True)
    return gate_ok


def filter_by_trend_gate(cands: List[Dict[str, Any]],
                         gate_ok: set) -> List[Dict[str, Any]]:
    return [c for c in cands
            if (c["ticker"], c["entry_date"]) in gate_ok]


# ─────────────────────────────────────────────────────────────────────
# Multi-signal week (R9) — keep only fires whose (ticker, ISO week) had
# ≥2 distinct signal_types fire among the raw (pre-dedup) fires.
# ─────────────────────────────────────────────────────────────────────
def build_multisig_week_set(raw_fires: List[Dict[str, Any]]) -> set:
    """Returns set of (ticker, ISO-week) with ≥2 distinct entry signals
    that week."""
    by_key: Dict[tuple, set] = {}
    sig_set = set(P.DEFAULT_ENTRY_SIGNALS)
    for f in raw_fires:
        if f.get("signal_type") not in sig_set:
            continue
        if f.get("direction") != "bullish":
            continue
        k = (f["ticker"], week_bucket(f["entry_date"]))
        by_key.setdefault(k, set()).add(f["signal_type"])
    return {k for k, sigs in by_key.items() if len(sigs) >= 2}


def filter_by_multisig(cands: List[Dict[str, Any]],
                       multi_set: set) -> List[Dict[str, Any]]:
    return [c for c in cands
            if (c["ticker"], week_bucket(c["entry_date"])) in multi_set]


# ─────────────────────────────────────────────────────────────────────
# Run one variant
# ─────────────────────────────────────────────────────────────────────
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
    liquidity = LiquidityLookup()
    pit_idx = build_pit_cap_index()

    exit_fires = [
        f for f in raw_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    delisting_dates = fetch_delisting_dates()
    print(f"exit fires: {len(exit_fires):,}, delisting: {len(delisting_dates):,}",
          flush=True)

    # Pre-build R8 / R9 indexes
    print("\nbuilding R8 trend gate index ...", flush=True)
    trend_gate = build_trend_gate_index()
    print("building R9 multi-signal week set ...", flush=True)
    multi_set = build_multisig_week_set(raw_fires_all)
    print(f"  multi-signal weeks: {len(multi_set):,} (ticker, week)", flush=True)

    # ─────────────────────────────────────────────────────────────
    # Variant list
    # ─────────────────────────────────────────────────────────────
    VARIANTS: List[Dict[str, Any]] = [
        # R5 — small-cap tilt + sector_cap=4 stack
        {
            "key": "R5_bw08_peak1k_cap4",
            "cands_fn": lambda: apply_variant(
                fires, cap_map, sector_map, max_strength,
                sector_cap_per_week=4, book_weight=0.8,
                pit_cap_index=pit_idx, cap_peak_krw=1e11,
            ),
        },
        # R8 — trend confirmation gate (sector_cap=1 base)
        {
            "key": "R8_trend_gate",
            "cands_fn": lambda: filter_by_trend_gate(
                apply_variant(fires, cap_map, sector_map, max_strength,
                              sector_cap_per_week=1, book_weight=1.0),
                trend_gate,
            ),
        },
        # R9 — multi-signal week agreement (sector_cap=1 base)
        {
            "key": "R9_multisig_week",
            "cands_fn": lambda: filter_by_multisig(
                apply_variant(fires, cap_map, sector_map, max_strength,
                              sector_cap_per_week=1, book_weight=1.0),
                multi_set,
            ),
        },
        # R10 — strength threshold sweep (sector_cap=1 base)
        {
            "key": "R10_min_str_05",
            "cands_fn": lambda: apply_variant(
                P.filter_entry_fires(raw_fires_all, P.DEFAULT_ENTRY_SIGNALS,
                                     min_strength=0.5),
                cap_map, sector_map, max_strength,
                sector_cap_per_week=1, book_weight=1.0,
            ),
        },
        {
            "key": "R10_min_str_06",
            "cands_fn": lambda: apply_variant(
                P.filter_entry_fires(raw_fires_all, P.DEFAULT_ENTRY_SIGNALS,
                                     min_strength=0.6),
                cap_map, sector_map, max_strength,
                sector_cap_per_week=1, book_weight=1.0,
            ),
        },
        {
            "key": "R10_min_str_07",
            "cands_fn": lambda: apply_variant(
                P.filter_entry_fires(raw_fires_all, P.DEFAULT_ENTRY_SIGNALS,
                                     min_strength=0.7),
                cap_map, sector_map, max_strength,
                sector_cap_per_week=1, book_weight=1.0,
            ),
        },
    ]

    out_rows = []
    for i, v in enumerate(VARIANTS, start=1):
        print(f"\n[{i}/{len(VARIANTS)}] {v['key']}", flush=True)
        cands = v["cands_fn"]()
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
            "variant": v["key"],
            "n_cands": len(cands),
            "n_trades": len(state.trades),
            "cagr": m["annualised_return_pct"],
            "sharpe": m["sharpe"], "sortino": m["sortino"],
            "dd_pct": m["max_drawdown_mtm_pct"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "outperf_ann": m.get("outperformance_ann_pct"),
        })

    out_path = ROOT / "data" / "grid_R5_R10_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>22} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} trades {r['n_trades']:>5}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
