"""R19 — 52-week price position filter.

Book 정신: 천장 가까운 자리에서 사지 말고 바닥/중간 부근에서.
For each fire at entry_date t, compute rel_pos = (close − 52w low) /
(52w high − 52w low) over the prior 52 weekly bars (PIT — no peek
beyond t). 0 = at 52w low, 1 = at 52w high.

Variants (all sector_cap=1 base):
  R19a : rel_pos < 0.3   (lower 30% — 책 권장)
  R19b : rel_pos < 0.5
  R19c : rel_pos < 0.7   (exclude top-30% only)
  R19d : 0.1 < rel_pos < 0.5  (no flat-bottom + lower half)
  R19e : 0.2 < rel_pos < 0.6  (mid zone)
  R19f : R19c (< 0.7) AND R17a (mom12 + mom26 pos) — combo
  R19g : R19b (< 0.5) AND mom26_pos
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict

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
)
from scripts.grid_R15_R16_momentum_quality import (
    build_features, index_features, filter_cands,
)


def build_position_index() -> Dict[str, Dict[str, float]]:
    """index[ticker][YYYY-MM-DD] = rel_pos (0..1) over last 52 weekly bars."""
    t0 = time.time()
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    rows = con.sql(
        "SELECT ticker, bar_date, close FROM bars "
        "WHERE granularity='W' ORDER BY ticker, bar_date"
    ).fetchall()
    con.close()
    df = pd.DataFrame(rows, columns=["ticker", "bar_date", "close"])
    df["bar_date"] = pd.to_datetime(df["bar_date"])
    df = df.sort_values(["ticker", "bar_date"]).reset_index(drop=True)
    df["hi_52"] = (df.groupby("ticker")["close"]
                   .transform(lambda s: s.rolling(52, min_periods=20).max()))
    df["lo_52"] = (df.groupby("ticker")["close"]
                   .transform(lambda s: s.rolling(52, min_periods=20).min()))
    rng = (df["hi_52"] - df["lo_52"]).clip(lower=1e-9)
    df["rel_pos"] = (df["close"] - df["lo_52"]) / rng
    idx: Dict[str, Dict[str, float]] = {}
    for tic, grp in df.groupby("ticker"):
        idx[tic] = {r.bar_date.date().isoformat(): float(r.rel_pos)
                    for r in grp.itertuples() if pd.notna(r.rel_pos)}
    print(f"  position index: {len(idx):,} tickers, "
          f"{sum(len(v) for v in idx.values()):,} rows in {time.time()-t0:.1f}s",
          flush=True)
    return idx


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

    print("building 52w position index ...", flush=True)
    pos_idx = build_position_index()
    print("building momentum features ...", flush=True)
    feat_df = build_features()
    feat_idx = index_features(feat_df)

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"\nbaseline cands: {len(cands_base):,}", flush=True)

    def get_rel_pos(c):
        return pos_idx.get(c["ticker"], {}).get(c["entry_date"])

    def filter_pos(cands, predicate):
        out = []
        for c in cands:
            rp = get_rel_pos(c)
            if rp is None:
                continue
            if predicate(rp):
                out.append(c)
        return out

    # Combo with momentum
    pos_pred = lambda key: (lambda f: f.get(key) is not None and f[key] > 0)
    mom_12_26 = lambda f: pos_pred("ret_12w")(f) and pos_pred("ret_26w")(f)
    mom_26 = pos_pred("ret_26w")

    VARIANTS = [
        ("R19a_pos_lt03",          lambda: filter_pos(cands_base, lambda rp: rp < 0.3)),
        ("R19b_pos_lt05",          lambda: filter_pos(cands_base, lambda rp: rp < 0.5)),
        ("R19c_pos_lt07",          lambda: filter_pos(cands_base, lambda rp: rp < 0.7)),
        ("R19d_pos_01_05",         lambda: filter_pos(cands_base, lambda rp: 0.1 < rp < 0.5)),
        ("R19e_pos_02_06",         lambda: filter_pos(cands_base, lambda rp: 0.2 < rp < 0.6)),
        ("R19f_pos_lt07_AND_mom",  lambda: filter_cands(
                                       filter_pos(cands_base, lambda rp: rp < 0.7),
                                       feat_idx, mom_12_26)),
        ("R19g_pos_lt05_AND_mom26",lambda: filter_cands(
                                       filter_pos(cands_base, lambda rp: rp < 0.5),
                                       feat_idx, mom_26)),
    ]

    out_rows = []
    # Baseline ref
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

    out_path = ROOT / "data" / "grid_R19_results.csv"
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
