"""Phase 5 — single-factor + combo grid over the L2 winner.

Baseline = Phase 4 L2 (book 0.8 + cap_tent_q 0.2, max=50, 24w, no SL).
This script adds three orthogonal candidates and tests each in
isolation + a final combo of the winners:

  A. Sector cap        — top-K (2/3) per industry within each entry week
  B. Liquidity gate    — drop fires with 4w turnover below floor (3억/10억/50억)
  C. Multi-TF bonus    — +α × n_distinct_timeframes for the (ticker, week)

Inputs:
  data/sweep_all_24w.csv      — 315k fires (24w fixed hold)
  data/market_caps_today.csv  — present-day cap snapshot
  data/kr_sectors.csv         — KR ticker → industry (161 categories)
  data/backtest.duckdb        — bars + liquidity_4w cache

Outputs:
  data/phase5_variants/<key>.json  — per-variant metrics + trade count
  data/phase5_summary.csv          — one row per variant

Usage:
  python scripts/grid_phase5_factors.py             # all 9 variants
  python scripts/grid_phase5_factors.py --only 11_sector_cap2
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import duckdb
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics

# ─────────────────────────────────────────────────────────────────────
# L2 baseline ranking — keep in sync with scripts/run_l2_production.py
# ─────────────────────────────────────────────────────────────────────
CAP_LOW = 5e10
CAP_HIGH = 1e13
LOG_LO = math.log10(CAP_LOW)
LOG_HI = math.log10(CAP_HIGH)
LOG_PEAK = (math.log10(3e11) + math.log10(1e12)) / 2

BOOK_W = 0.8
CAP_W = 0.2


def cap_q(mc: Optional[float]) -> float:
    if mc is None or mc <= 0:
        return 0.0
    lc = math.log10(mc)
    if lc <= LOG_LO or lc >= LOG_HI:
        return 0.0
    if lc <= LOG_PEAK:
        return (lc - LOG_LO) / (LOG_PEAK - LOG_LO)
    return (LOG_HI - lc) / (LOG_HI - LOG_PEAK)


def load_cap_map() -> Dict[str, float]:
    csv_path = ROOT / "data" / "market_caps_today.csv"
    out: Dict[str, float] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            v = (row.get("market_cap_krw") or "").strip()
            if v:
                try:
                    out[row["ticker"]] = float(v)
                except ValueError:
                    pass
    return out


# ─────────────────────────────────────────────────────────────────────
# PIT cap reconstruction — today's shares × historical adj_close.
#
# Honest about the limitation: KR ticker share counts can grow over
# time (유상증자 / CB 전환). Today's shares ≥ historical shares for
# most firms, so multiplying historical close by today's shares
# OVER-estimates historical cap by the dilution factor. Most KR firms
# dilute < 50% over a decade — far smaller bias than the static
# today-cap baseline that ignores price changes entirely.
#
# Splits are auto-handled: bars.close is already split-adjusted in the
# local DuckDB (verified by Samsung 2018-05 50:1 split — close stayed
# ~50K across split date, not 2.5M → 50K jump).
# ─────────────────────────────────────────────────────────────────────
def build_pit_cap_index() -> Dict[str, List[Tuple[date, float]]]:
    """Per-ticker (weekly_date, cap_krw_proxy) sorted by date.

    cap = shares_today × close_at(date). adj_close is already
    split-adjusted so no factor needed. Returns dict[ticker] → list
    of (date, cap) for binary-search lookups during rerank.
    """
    import pandas as pd
    t0 = time.time()
    shares_df = pd.read_parquet(ROOT / "data" / "kr_shares_current.parquet")
    shares_map: Dict[str, float] = {
        r["ticker"]: float(r["shares_current"])
        for _, r in shares_df.iterrows()
        if r.get("shares_current") and r["shares_current"] > 0
    }
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    rows = con.sql(
        "SELECT ticker, bar_date, close FROM bars "
        "WHERE granularity='W' AND close IS NOT NULL"
    ).fetchall()
    con.close()
    out: Dict[str, List[Tuple[date, float]]] = defaultdict(list)
    for ticker, bdate, close in rows:
        shares = shares_map.get(ticker)
        if shares is None:
            continue
        out[ticker].append((bdate, shares * float(close)))
    for t in out:
        out[t].sort()
    print(f"  PIT cap index: {sum(len(v) for v in out.values()):,} (ticker, week) "
          f"caps / {len(out):,} tickers in {time.time()-t0:.1f}s",
          flush=True)
    return out


def pit_cap_at(
    idx: Dict[str, List[Tuple[date, float]]],
    ticker: str, entry_date: date,
) -> Optional[float]:
    lst = idx.get(ticker)
    if not lst:
        return None
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi) // 2
        if lst[mid][0] <= entry_date:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    return lst[lo - 1][1]


def load_sector_map() -> Dict[str, str]:
    csv_path = ROOT / "data" / "kr_sectors.csv"
    out: Dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            ind = (row.get("industry") or "").strip()
            if ind:
                out[row["ticker"]] = ind
    return out


# ─────────────────────────────────────────────────────────────────────
# Liquidity gate — DuckDB lookup (4-week rolling turnover)
# ─────────────────────────────────────────────────────────────────────
class LiquidityLookup:
    """Find the most recent weekly turnover ≤ entry_date for each
    (ticker, entry_date). The fire CSV's entry_date is the weekly bar
    end. Loads all once into a dict for O(1) lookup at sim time."""

    def __init__(self) -> None:
        t0 = time.time()
        con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                             read_only=True)
        rows = con.sql(
            "SELECT ticker, bar_date, turnover_4w_krw "
            "FROM liquidity_4w WHERE turnover_4w_krw IS NOT NULL"
        ).fetchall()
        con.close()
        # Build {ticker: sorted list of (date, turnover)}
        self._by_ticker: Dict[str, List[Tuple[date, float]]] = defaultdict(list)
        for t, d, v in rows:
            self._by_ticker[t].append((d, float(v)))
        for t in self._by_ticker:
            self._by_ticker[t].sort()
        print(f"  liquidity index: {len(rows):,} rows / "
              f"{len(self._by_ticker):,} tickers in {time.time()-t0:.1f}s",
              flush=True)

    def turnover_at(self, ticker: str, entry_date: date) -> Optional[float]:
        lst = self._by_ticker.get(ticker)
        if not lst:
            return None
        # Find rightmost entry with bar_date <= entry_date.
        lo, hi = 0, len(lst)
        while lo < hi:
            mid = (lo + hi) // 2
            if lst[mid][0] <= entry_date:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        return lst[lo - 1][1]


# ─────────────────────────────────────────────────────────────────────
# Reranking + filtering per variant config
# ─────────────────────────────────────────────────────────────────────
def baseline_score(book_norm: float, cap_q_value: float) -> float:
    return BOOK_W * book_norm + CAP_W * cap_q_value


def week_bucket(d_iso: str) -> str:
    """YYYY-MM-DD → ISO year-week for grouping multi-TF + sector cap."""
    d = date.fromisoformat(d_iso)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def apply_variant(
    fires: List[Dict[str, Any]],
    cap_map: Dict[str, float],
    sector_map: Dict[str, str],
    max_strength: float,
    *,
    liquidity_floor_krw: float = 0.0,
    liquidity: Optional[LiquidityLookup] = None,
    multitf_bonus: float = 0.0,
    sector_cap_per_week: int = 0,    # 0 = disabled
    weekly_top_k: int = 50,          # within-week cap before sector cap
    book_weight: Optional[float] = None,   # None = use module BOOK_W
    max_positions: int = 50,         # unused here, kept for cfg passthrough
    pit_cap_index: Optional[Dict[str, List[Tuple[date, float]]]] = None,
    # When pit_cap_index is provided, look up cap at each fire's
    # entry_date instead of using the static today snapshot.
) -> List[Dict[str, Any]]:
    """Return a new list of re-ranked, gate-filtered candidates."""
    # 1. liquidity gate
    if liquidity_floor_krw > 0 and liquidity is not None:
        kept = []
        for f in fires:
            tv = liquidity.turnover_at(f["ticker"], date.fromisoformat(f["entry_date"]))
            if tv is not None and tv >= liquidity_floor_krw:
                kept.append(f)
        fires = kept

    # 2. multi-TF: count distinct timeframes per (ticker, week)
    if multitf_bonus > 0:
        tf_count: Dict[Tuple[str, str], int] = defaultdict(int)
        per_key: Dict[Tuple[str, str], set] = defaultdict(set)
        for f in fires:
            k = (f["ticker"], week_bucket(f["entry_date"]))
            per_key[k].add(f.get("timeframe", "daily"))
        for k, tfs in per_key.items():
            tf_count[k] = len(tfs)
    else:
        tf_count = {}

    # 3. composite score
    bw = BOOK_W if book_weight is None else float(book_weight)
    cw = 1.0 - bw
    rescored: List[Dict[str, Any]] = []
    for f in fires:
        s = float(f.get("strength", 0))
        s_n = s / max_strength if max_strength > 0 else 0.0
        if pit_cap_index is not None:
            mc = pit_cap_at(pit_cap_index, f["ticker"],
                            date.fromisoformat(f["entry_date"]))
        else:
            mc = cap_map.get(f["ticker"])
        q = cap_q(mc) if cw > 0 else 0.0
        score = bw * s_n + cw * q
        if multitf_bonus > 0:
            k = (f["ticker"], week_bucket(f["entry_date"]))
            n_tf = tf_count.get(k, 1)
            # Bonus only when n_tf >= 2 (lifts agreeing signals).
            if n_tf >= 2:
                score += multitf_bonus * min(n_tf - 1, 2) / 2.0
        new_f = dict(f)
        new_f["strength"] = score
        rescored.append(new_f)

    # 4. sector cap per week
    if sector_cap_per_week > 0:
        # Group by week, sort each week by strength desc, take top-K
        # subject to ≤sector_cap_per_week per industry.
        by_week: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for f in rescored:
            by_week[week_bucket(f["entry_date"])].append(f)
        capped: List[Dict[str, Any]] = []
        for wk, items in by_week.items():
            items.sort(key=lambda x: float(x.get("strength", 0)), reverse=True)
            kept_per_sec: Dict[str, int] = defaultdict(int)
            kept_total = 0
            for it in items:
                sec = sector_map.get(it["ticker"], "_UNKNOWN")
                if kept_per_sec[sec] >= sector_cap_per_week:
                    continue
                kept_per_sec[sec] += 1
                kept_total += 1
                capped.append(it)
                if kept_total >= weekly_top_k:
                    break
        return capped

    return rescored


# ─────────────────────────────────────────────────────────────────────
# Variants
# ─────────────────────────────────────────────────────────────────────
VARIANTS: Dict[str, Dict[str, Any]] = {
    "00_baseline_L2": dict(),
    # Sector cap (industry)
    "11_sector_cap2": dict(sector_cap_per_week=2),
    "12_sector_cap1": dict(sector_cap_per_week=1),
    # Liquidity gate
    "21_liq_3억": dict(liquidity_floor_krw=3e8),
    "22_liq_10억": dict(liquidity_floor_krw=1e9),
    "23_liq_50억": dict(liquidity_floor_krw=5e9),
    # Multi-TF bonus
    "31_multitf_low": dict(multitf_bonus=0.05),
    "32_multitf_high": dict(multitf_bonus=0.15),
    # Compound — applied after Phase 1 results (placeholder, may swap)
    "41_combo_sec2_liq10_mtf05":
        dict(sector_cap_per_week=2, liquidity_floor_krw=1e9, multitf_bonus=0.05),
    # ─── Phase 6 — fine-tune around sector_cap=1 winner ─────────────
    # sector_cap=1 in Phase 5 ⇒ CAGR +21.89 / Sharpe 0.87 / Alpha +12.18.
    # Now isolate which lever pushes further: weekly_top_k, book_weight,
    # max_positions, or stacked liquidity.
    "51_cap1_topk30":
        dict(sector_cap_per_week=1, weekly_top_k=30),
    "52_cap1_topk100":
        dict(sector_cap_per_week=1, weekly_top_k=100),
    "53_cap1_bookw07":
        dict(sector_cap_per_week=1, book_weight=0.7),
    "54_cap1_bookw09":
        dict(sector_cap_per_week=1, book_weight=0.9),
    "55_cap1_liq5억":
        dict(sector_cap_per_week=1, liquidity_floor_krw=5e8),
    "56_cap2_maxpos30":
        dict(sector_cap_per_week=2, max_positions=30),
    "57_cap1_maxpos30":
        dict(sector_cap_per_week=1, max_positions=30),
    # ─── Phase 7 — push around (cap1, book_weight≈0.7) ───────────────
    # Phase 6 winner = cap1 + bookw07 (CAGR +22.77, Sharpe 0.89, Alpha +13.09).
    # Sweep book_weight finer + combine with second-place top_k=100.
    "61_cap1_bookw06":
        dict(sector_cap_per_week=1, book_weight=0.6),
    "62_cap1_bookw065":
        dict(sector_cap_per_week=1, book_weight=0.65),
    "63_cap1_bookw075":
        dict(sector_cap_per_week=1, book_weight=0.75),
    "64_cap1_bookw05":
        dict(sector_cap_per_week=1, book_weight=0.5),
    "65_cap1_bookw07_topk100":
        dict(sector_cap_per_week=1, book_weight=0.7, weekly_top_k=100),
    "66_cap1_bookw06_topk100":
        dict(sector_cap_per_week=1, book_weight=0.6, weekly_top_k=100),
    "67_cap1_bookw07_topk75":
        dict(sector_cap_per_week=1, book_weight=0.7, weekly_top_k=75),
    "68_cap1_bookw07_maxpos60":
        dict(sector_cap_per_week=1, book_weight=0.7, max_positions=60),
    # ─── Phase 8 — fine sweep around bookw=0.75 winner ──────────────
    "71_cap1_bookw0725":
        dict(sector_cap_per_week=1, book_weight=0.725),
    "72_cap1_bookw0775":
        dict(sector_cap_per_week=1, book_weight=0.775),
    "73_cap1_bookw078":
        dict(sector_cap_per_week=1, book_weight=0.78),
    "74_cap1_bookw075_maxpos60":
        dict(sector_cap_per_week=1, book_weight=0.75, max_positions=60),
    "75_cap1_bookw075_maxpos40":
        dict(sector_cap_per_week=1, book_weight=0.75, max_positions=40),
    "76_cap1_bookw075_topk100":
        dict(sector_cap_per_week=1, book_weight=0.75, weekly_top_k=100),
    "77_cap2_bookw075":
        dict(sector_cap_per_week=2, book_weight=0.75),
    "78_cap1_bookw075_liq3억":
        dict(sector_cap_per_week=1, book_weight=0.75, liquidity_floor_krw=3e8),

    # ─── Phase 9 — PIT cap reconstruction (today's shares ×
    #                historical adj_close) for honest look-ahead test ──
    # Re-run each Phase winner with use_pit_cap=True so cap_q reads
    # from per-week historical proxy instead of the today snapshot.
    # Compare delta with the corresponding non-PIT variant to size
    # the look-ahead bias.
    "P9_00_baseline_PIT":
        dict(use_pit_cap=True),
    "P9_12_cap1_PIT":
        dict(sector_cap_per_week=1, use_pit_cap=True),
    "P9_53_cap1_bookw07_PIT":
        dict(sector_cap_per_week=1, book_weight=0.7, use_pit_cap=True),
    "P9_63_cap1_bookw075_PIT":
        dict(sector_cap_per_week=1, book_weight=0.75, use_pit_cap=True),
    "P9_73_cap1_bookw078_PIT":
        dict(sector_cap_per_week=1, book_weight=0.78, use_pit_cap=True),
    "P9_78_cap1_bookw075_liq3억_PIT":
        dict(sector_cap_per_week=1, book_weight=0.75,
             liquidity_floor_krw=3e8, use_pit_cap=True),

    # Controls — set cap_q to ZERO (book_weight=1.0) to isolate the
    # pure sector_cap + book-signal effect with no cap contribution.
    # If a "no cap_q" variant still beats baseline, the sector cap
    # delivers real lift regardless of cap_q look-ahead.
    "C_baseline_book1":
        dict(book_weight=1.0),
    "C_cap1_book1":
        dict(sector_cap_per_week=1, book_weight=1.0),
}


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────
def run_one(
    key: str, cfg: Dict[str, Any],
    base_fires: List[Dict[str, Any]],
    cap_map: Dict[str, float],
    sector_map: Dict[str, str],
    liquidity: LiquidityLookup,
    max_strength: float,
    start: date, end: date,
    pit_cap_index: Optional[Dict[str, List[Tuple[date, float]]]] = None,
) -> Dict[str, Any]:
    print(f"\n[{key}] config={cfg}", flush=True)
    t0 = time.time()
    t1 = time.time()
    use_pit = bool(cfg.pop("use_pit_cap", False)) if "use_pit_cap" in cfg else False
    cands = apply_variant(
        base_fires, cap_map, sector_map, max_strength,
        liquidity=liquidity,
        pit_cap_index=(pit_cap_index if use_pit else None),
        **cfg,
    )
    print(f"  candidates after filter/rerank: {len(cands):,} ({time.time()-t1:.1f}s)",
          flush=True)
    t2 = time.time()
    max_pos = int(cfg.get("max_positions", 50))
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0,
        max_positions=max_pos,
        stop_loss_pct=0.0,
    )
    print(f"  simulate done: trades={len(state.trades):,} ({time.time()-t2:.1f}s)",
          flush=True)
    t3 = time.time()
    elapsed = time.time() - t0
    m = compute_full_metrics(state, start, end)
    print(f"  metrics done ({time.time()-t3:.1f}s)", flush=True)
    print(f"  done {elapsed:.0f}s: trades={len(state.trades):,} "
          f"CAGR={m['annualised_return_pct']:+.2f}% "
          f"Sharpe={m['sharpe']:.2f} "
          f"DD={m['max_drawdown_mtm_pct']:.1f}% "
          f"Alpha={m.get('alpha_annual_pct'):+.2f}%/y",
          flush=True)
    out = ROOT / "data" / "phase5_variants" / f"{key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fp:
        json.dump({
            "key": key, "config": cfg,
            "start": start.isoformat(), "end": end.isoformat(),
            "n_candidates": len(cands),
            "n_trades": len(state.trades),
            "elapsed_sec": round(elapsed, 1),
            "metrics": m,
        }, fp, indent=2, default=str)
    return {
        "key": key,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "calmar": m["calmar"],
        "max_dd_mtm": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "elapsed_sec": round(elapsed, 1),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append",
                   help="run just these variant keys (repeatable)")
    p.add_argument("--start", default="2009-01-01")
    p.add_argument("--end", default="2026-05-22")
    args = p.parse_args(argv)

    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    print("loading aux maps ...", flush=True)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    print(f"  cap_map={len(cap_map):,}  sector_map={len(sector_map):,}",
          flush=True)
    liquidity = LiquidityLookup()
    pit_cap_index = build_pit_cap_index()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    keys = list(VARIANTS.keys())
    if args.only:
        keys = [k for k in keys if k in set(args.only)]

    rows: List[Dict[str, Any]] = []
    for k in keys:
        rows.append(run_one(
            k, dict(VARIANTS[k]), fires, cap_map, sector_map,
            liquidity, max_strength, start, end,
            pit_cap_index=pit_cap_index,
        ))

    # Summary CSV
    summary = ROOT / "data" / "phase5_summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(
            fp, fieldnames=["key", "n_trades", "cagr", "sharpe", "calmar",
                            "max_dd_mtm", "alpha_ann", "elapsed_sec"],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote summary → {summary}", flush=True)
    print("\nRANKING (by Sharpe desc):", flush=True)
    rows.sort(key=lambda r: -(r["sharpe"] or 0))
    print(f"  {'variant':<32} {'CAGR':>8} {'Sharpe':>7} {'DD':>7} {'Alpha':>8}")
    for r in rows:
        print(f"  {r['key']:<32} {r['cagr']:+7.2f}% {r['sharpe']:6.2f} "
              f"{r['max_dd_mtm']:6.1f}% {r['alpha_ann']:+7.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
