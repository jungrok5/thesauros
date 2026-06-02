"""R15-R16 — momentum + entry-bar quality factors on v1.1 universe.

R15 — 발화 시점 직전 N주 수익률 (momentum) 을 ranking score 에 가산.
       가설: 같은 책 신호 중 직전 +momentum 종목 선호 (추세 확인).

R16 — entry 주봉 quality:
       - 거래량 surge: entry-bar volume / 20-bar median volume
       - 종가 위치: (close - low) / (high - low)  (1.0 = 최고가 마감)
       - body strength: body / range

variants:
  R15a/b/c: momentum window 4w/12w/26w, gate ≥ 0 (positive momentum 만)
  R15d/e/f: same windows, gate ≥ +5% (lift bar)
  R16a:    high vol-surge (>1.5x median), score-additive
  R16b:    high close position (>0.7), gate
  R16c:    high body strength (>0.5), gate
  R16d:    composite — all 3 R16 gates AND

Each runs sector_cap=1 baseline + filter. Tests if pre-rank quality
filter lifts alpha without over-fitting.

Output: data/grid_R15_R16_results.csv
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ─────────────────────────────────────────────────────────────────────
# Pre-compute per-ticker weekly bars with momentum + quality features
# ─────────────────────────────────────────────────────────────────────
def build_features() -> Dict[str, pd.DataFrame]:
    """Load weekly bars per ticker with momentum + quality columns."""
    t0 = time.time()
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    rows = con.sql(
        "SELECT ticker, bar_date, open, high, low, close, volume "
        "FROM bars WHERE granularity='W' ORDER BY ticker, bar_date"
    ).fetchall()
    con.close()
    df = pd.DataFrame(rows, columns=["ticker", "bar_date", "open",
                                     "high", "low", "close", "volume"])
    df["bar_date"] = pd.to_datetime(df["bar_date"])
    df = df.sort_values(["ticker", "bar_date"]).reset_index(drop=True)
    df["ret_4w"] = df.groupby("ticker")["close"].pct_change(4)
    df["ret_12w"] = df.groupby("ticker")["close"].pct_change(12)
    df["ret_26w"] = df.groupby("ticker")["close"].pct_change(26)
    df["vol_20med"] = (df.groupby("ticker")["volume"]
                       .transform(lambda s: s.rolling(20, min_periods=10).median()))
    df["vol_surge"] = df["volume"] / df["vol_20med"]
    rng = (df["high"] - df["low"]).clip(lower=1e-9)
    df["close_pos"] = (df["close"] - df["low"]) / rng
    body = (df["close"] - df["open"]).abs()
    df["body_strength"] = body / rng
    print(f"  features built: {len(df):,} rows in {time.time()-t0:.1f}s",
          flush=True)
    return df


def index_features(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """index[ticker][YYYY-MM-DD] = feature dict for binary lookup."""
    idx: Dict[str, Dict[str, Any]] = {}
    for tic, grp in df.groupby("ticker"):
        idx[tic] = {
            r.bar_date.date().isoformat(): {
                "ret_4w": r.ret_4w,
                "ret_12w": r.ret_12w,
                "ret_26w": r.ret_26w,
                "vol_surge": r.vol_surge,
                "close_pos": r.close_pos,
                "body_strength": r.body_strength,
            }
            for r in grp.itertuples()
        }
    return idx


def filter_cands(
    cands: List[Dict[str, Any]],
    idx: Dict[str, Dict[str, Any]],
    predicate,
) -> List[Dict[str, Any]]:
    out = []
    for c in cands:
        feat = idx.get(c["ticker"], {}).get(c["entry_date"])
        if feat is None:
            continue
        if predicate(feat):
            out.append(c)
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

    print("building per-bar momentum + quality features ...", flush=True)
    feat_df = build_features()
    print("indexing features ...", flush=True)
    feat_idx = index_features(feat_df)
    print(f"  indexed: {len(feat_idx):,} tickers", flush=True)

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"baseline cands (sector_cap=1): {len(cands_base):,}", flush=True)

    # ─────────────────────────────────────────────────────────────
    # Variant defs
    # ─────────────────────────────────────────────────────────────
    pos_4w  = lambda f: f["ret_4w"]  is not None and f["ret_4w"]  > 0
    pos_12w = lambda f: f["ret_12w"] is not None and f["ret_12w"] > 0
    pos_26w = lambda f: f["ret_26w"] is not None and f["ret_26w"] > 0

    p5_4w  = lambda f: f["ret_4w"]  is not None and f["ret_4w"]  > 0.05
    p5_12w = lambda f: f["ret_12w"] is not None and f["ret_12w"] > 0.05
    p5_26w = lambda f: f["ret_26w"] is not None and f["ret_26w"] > 0.05

    vol_hi  = lambda f: f["vol_surge"]     is not None and f["vol_surge"] > 1.5
    cls_hi  = lambda f: f["close_pos"]     is not None and f["close_pos"] > 0.7
    body_hi = lambda f: f["body_strength"] is not None and f["body_strength"] > 0.5
    combo3  = lambda f: vol_hi(f) and cls_hi(f) and body_hi(f)

    VARIANTS = [
        ("R15a_mom4w_pos",   pos_4w),
        ("R15b_mom12w_pos",  pos_12w),
        ("R15c_mom26w_pos",  pos_26w),
        ("R15d_mom4w_5pct",  p5_4w),
        ("R15e_mom12w_5pct", p5_12w),
        ("R15f_mom26w_5pct", p5_26w),
        ("R16a_vol_surge_15x",   vol_hi),
        ("R16b_close_top30pct",  cls_hi),
        ("R16c_body_strong_50pct", body_hi),
        ("R16d_combo3_AND",      combo3),
    ]

    out_rows = []
    # Baseline first for reference
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

    for i, (key, pred) in enumerate(VARIANTS, start=1):
        print(f"\n[{i}/{len(VARIANTS)}] {key}", flush=True)
        cands = filter_cands(cands_base, feat_idx, pred)
        print(f"  cands after filter: {len(cands):,}", flush=True)
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

    out_path = ROOT / "data" / "grid_R15_R16_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>27} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} trades {r['n_trades']:>5}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
