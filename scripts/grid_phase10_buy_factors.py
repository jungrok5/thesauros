"""Phase 10 — PIT-safe buy-factor grid on top of book-faithful exits.

Sell rules stay locked (월봉 10MA / 4등분 25% / 천장 패턴). This sweep
asks: are there entry-time-only factors that improve the buy ranking
without re-introducing look-ahead?

Candidate factors (all computable from data available at entry_date —
no peek at future):
  signal_count   — how many of the book's top-5 signals fire on
                   (ticker, entry_week). 책 정신: 다중 confluence.
  volume_rel     — entry bar weekly volume / rolling 20-week avg.
                   책 5장: 거래량 동반 상승.
  body_strength  — entry bar body / rolling 20-week avg body (clamped
                   at 5). 책 엔진 장대양봉 graduation.

Each factor adds a bounded bonus to the score:
    score = book_score + sum(weight_i * factor_i)

Pipeline:
  1. Pre-compute factor values per candidate (one ticker scan each).
  2. Apply factor weights → re-rank → sector_cap=1.
  3. Run book-faithful simulate (max=20, 1억 capital).
  4. Report metrics.

Walk-forward verification is in scripts/walk_forward_phase10.py.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from scripts.grid_phase5_factors import (
    load_sector_map, LiquidityLookup, week_bucket,
)


# ─────────────────────────────────────────────────────────────────────
# Factor precomputation
# ─────────────────────────────────────────────────────────────────────
def build_signal_count(
    raw_fires: List[Dict[str, Any]],
    entry_signals: Tuple[str, ...],
) -> Dict[Tuple[str, str], int]:
    """{(ticker, week): n_distinct_top5_signals_firing}. Only the book's
    5 entry signals count toward the stack."""
    sig_set = set(entry_signals)
    per_key: Dict[Tuple[str, str], set] = defaultdict(set)
    for f in raw_fires:
        if f.get("signal_type") not in sig_set:
            continue
        if f.get("direction") != "bullish":
            continue
        k = (f["ticker"], week_bucket(f["entry_date"]))
        per_key[k].add(f["signal_type"])
    return {k: len(v) for k, v in per_key.items()}


def build_volume_and_body(
    distinct_tickers: List[str],
) -> Tuple[
    Dict[str, List[Tuple[date, float, float]]],
    Dict[str, List[Tuple[date, float, float]]],
]:
    """Two dicts keyed by ticker:
       vol_idx[ticker]  = [(date, vol_rel, _)] sorted ASC
       body_idx[ticker] = [(date, body_rel, _)] sorted ASC
    vol_rel  = volume / rolling 20w avg volume  (capped 5)
    body_rel = |close-open| / rolling 20w avg body  (capped 5)
    """
    t0 = time.time()
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"), read_only=True)
    rows = con.sql(
        "SELECT ticker, bar_date, open, close, volume "
        "FROM bars WHERE granularity='W' AND ticker = ANY(?) "
        "ORDER BY ticker, bar_date",
        params=[distinct_tickers],
    ).fetchall()
    con.close()
    per_t: Dict[str, List[Tuple[date, float, float, int]]] = defaultdict(list)
    for tic, d, o, c, v in rows:
        if o is None or c is None or v is None:
            continue
        per_t[tic].append((d, float(o), float(c), int(v)))
    vol_idx: Dict[str, List[Tuple[date, float, float]]] = {}
    body_idx: Dict[str, List[Tuple[date, float, float]]] = {}
    for tic, bars in per_t.items():
        recent_vols: List[int] = []
        recent_bodies: List[float] = []
        vol_list: List[Tuple[date, float, float]] = []
        body_list: List[Tuple[date, float, float]] = []
        for d, o, c, v in bars:
            avg_v = sum(recent_vols) / len(recent_vols) if recent_vols else 0
            avg_b = sum(recent_bodies) / len(recent_bodies) if recent_bodies else 0
            body = abs(c - o)
            vr = min(v / avg_v, 5.0) if avg_v > 0 else 0.0
            br = min(body / avg_b, 5.0) if avg_b > 0 else 0.0
            vol_list.append((d, vr, float(v)))
            body_list.append((d, br, body))
            recent_vols.append(v)
            recent_bodies.append(body)
            if len(recent_vols) > 20:
                recent_vols.pop(0)
            if len(recent_bodies) > 20:
                recent_bodies.pop(0)
        vol_idx[tic] = vol_list
        body_idx[tic] = body_list
    print(f"  vol+body index: {len(per_t):,} tickers in {time.time()-t0:.1f}s",
          flush=True)
    return vol_idx, body_idx


def _bisect_at(
    idx: List[Tuple[date, float, float]], target: date,
) -> Optional[Tuple[date, float, float]]:
    lo, hi = 0, len(idx)
    while lo < hi:
        mid = (lo + hi) // 2
        if idx[mid][0] <= target:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    return idx[lo - 1]


# ─────────────────────────────────────────────────────────────────────
# Apply factor weights + sector_cap
# ─────────────────────────────────────────────────────────────────────
def build_candidates(
    fires: List[Dict[str, Any]],
    sector_map: Dict[str, str],
    max_strength: float,
    sig_count_idx: Dict[Tuple[str, str], int],
    vol_idx: Dict[str, List[Tuple[date, float, float]]],
    body_idx: Dict[str, List[Tuple[date, float, float]]],
    *,
    w_signal_count: float = 0.0,
    w_volume_rel: float = 0.0,
    w_body_strength: float = 0.0,
) -> List[Dict[str, Any]]:
    # 1. rescore
    rescored: List[Dict[str, Any]] = []
    for f in fires:
        s = float(f.get("strength", 0))
        s_n = s / max_strength if max_strength > 0 else 0.0
        score = s_n
        if w_signal_count > 0:
            k = (f["ticker"], week_bucket(f["entry_date"]))
            n = sig_count_idx.get(k, 1)
            score += w_signal_count * (n - 1)        # +bonus when 2+
        ed = date.fromisoformat(f["entry_date"])
        if w_volume_rel > 0 and f["ticker"] in vol_idx:
            hit = _bisect_at(vol_idx[f["ticker"]], ed)
            if hit is not None:
                score += w_volume_rel * max(0.0, hit[1] - 1.0)
        if w_body_strength > 0 and f["ticker"] in body_idx:
            hit = _bisect_at(body_idx[f["ticker"]], ed)
            if hit is not None:
                score += w_body_strength * max(0.0, hit[1] - 1.0)
        new_f = dict(f)
        new_f["strength"] = score
        rescored.append(new_f)
    # 2. sector_cap=1 per week (book-faithful production default)
    by_week: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in rescored:
        by_week[week_bucket(f["entry_date"])].append(f)
    out: List[Dict[str, Any]] = []
    for wk, items in by_week.items():
        items.sort(key=lambda x: float(x.get("strength", 0)), reverse=True)
        kept: Dict[str, int] = defaultdict(int)
        total = 0
        for it in items:
            sec = sector_map.get(it["ticker"], "_UNKNOWN")
            if kept[sec] >= 1:
                continue
            kept[sec] += 1
            total += 1
            out.append(it)
            if total >= 50:
                break
    return out


# ─────────────────────────────────────────────────────────────────────
# Variants
# ─────────────────────────────────────────────────────────────────────
VARIANTS: Dict[str, Dict[str, float]] = {
    "P10_00_baseline": {},
    "P10_11_sig_count_05": dict(w_signal_count=0.05),
    "P10_12_sig_count_10": dict(w_signal_count=0.10),
    "P10_13_sig_count_15": dict(w_signal_count=0.15),
    "P10_21_volume_05": dict(w_volume_rel=0.05),
    "P10_22_volume_10": dict(w_volume_rel=0.10),
    "P10_23_volume_15": dict(w_volume_rel=0.15),
    "P10_31_body_05": dict(w_body_strength=0.05),
    "P10_32_body_10": dict(w_body_strength=0.10),
    "P10_33_body_15": dict(w_body_strength=0.15),
    "P10_41_sig_vol": dict(w_signal_count=0.10, w_volume_rel=0.10),
    "P10_42_sig_body": dict(w_signal_count=0.10, w_body_strength=0.10),
    "P10_43_vol_body": dict(w_volume_rel=0.10, w_body_strength=0.10),
    "P10_44_all3": dict(w_signal_count=0.10, w_volume_rel=0.10, w_body_strength=0.10),
}


def run(
    key: str, cfg: Dict[str, float],
    fires, raw_for_count, sector_map, max_strength,
    sig_count_idx, vol_idx, body_idx, exit_fires,
    start: date, end: date,
) -> Dict[str, Any]:
    print(f"\n[{key}] {cfg}", flush=True)
    t0 = time.time()
    cands = build_candidates(
        fires, sector_map, max_strength,
        sig_count_idx, vol_idx, body_idx,
        **cfg,
    )
    print(f"  cands={len(cands):,}", flush=True)
    reset_caches()
    state = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
    )
    m = compute_full_metrics(state, start, end)
    print(f"  done {time.time()-t0:.0f}s: trades={len(state.trades):,} "
          f"CAGR={m['annualised_return_pct']:+.2f} "
          f"Sharpe={m['sharpe']:.2f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f}", flush=True)
    return {
        "key": key, "config": cfg,
        "n_trades": len(state.trades),
        "metrics": {k: m.get(k) for k in [
            "annualised_return_pct", "sharpe", "sortino", "calmar",
            "max_drawdown_mtm_pct", "alpha_annual_pct",
            "outperformance_ann_pct", "total_return_pct",
        ]},
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append")
    p.add_argument("--start", default="2009-01-01")
    p.add_argument("--end", default="2026-05-22")
    args = p.parse_args()

    print("loading fires + indices ...", flush=True)
    raw_fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    entry_fires = P.filter_entry_fires(raw_fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in entry_fires)
    sector_map = load_sector_map()
    sig_count_idx = build_signal_count(raw_fires, P.DEFAULT_ENTRY_SIGNALS)
    distinct = sorted({f["ticker"] for f in entry_fires})
    vol_idx, body_idx = build_volume_and_body(distinct)
    exit_fires = [
        f for f in raw_fires
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    print(f"  entry fires={len(entry_fires):,} exit fires={len(exit_fires):,}",
          flush=True)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    keys = list(VARIANTS.keys())
    if args.only:
        keys = [k for k in keys if k in set(args.only)]

    rows: List[Dict[str, Any]] = []
    for k in keys:
        r = run(
            k, VARIANTS[k], entry_fires, raw_fires, sector_map, max_strength,
            sig_count_idx, vol_idx, body_idx, exit_fires,
            start, end,
        )
        rows.append(r)
        out = ROOT / "data" / "phase10_variants" / f"{k}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fp:
            json.dump(r, fp, indent=2, default=str)

    rows.sort(key=lambda r: -(r["metrics"]["sharpe"] or 0))
    print("\nRANKING (by Sharpe desc):")
    print(f"  {'variant':<32} {'CAGR':>8} {'Sharpe':>7} {'DD':>7} {'Alpha':>8} trades")
    for r in rows:
        m = r["metrics"]
        print(f"  {r['key']:<32} {m['annualised_return_pct']:+7.2f}% "
              f"{m['sharpe']:6.2f} {m['max_drawdown_mtm_pct']:6.1f}% "
              f"{m.get('alpha_annual_pct'):+7.2f}% {r['n_trades']:>6}")

    summary = ROOT / "data" / "phase10_summary.csv"
    with summary.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "key", "n_trades", "cagr", "sharpe", "calmar",
            "max_dd", "alpha_ann",
        ])
        w.writeheader()
        for r in rows:
            m = r["metrics"]
            w.writerow({
                "key": r["key"], "n_trades": r["n_trades"],
                "cagr": m["annualised_return_pct"],
                "sharpe": m["sharpe"],
                "calmar": m["calmar"],
                "max_dd": m["max_drawdown_mtm_pct"],
                "alpha_ann": m.get("alpha_annual_pct"),
            })
    print(f"\nwrote {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
