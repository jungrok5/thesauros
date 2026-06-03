"""R14 — 외국인/기관 누적 매수 PIT factor grid.

Naver investor_flow has 9.3M rows / 2,701 tickers / 2005-2026 covering
the full backtest window. For each fire at entry_date t, compute the
cumulative net buy (KRW) by foreigners + institutions over the prior
N days (PIT safe — only day < t).

Hypothesis: 책 신호 발화 시점에 외국인/기관 자금이 들어오고 있는 종목
이 더 강한 매수 자리. 단순 long-only momentum 보다 "스마트 머니" 일치
가 OOS 에서도 generalize 할 가능성.

Variants:
  R14a: prior_4w_foreign_net > 0   (4주 외국인 누적 매수 양수)
  R14b: prior_12w_foreign_net > 0
  R14c: prior_4w_foreign + 4w_inst 둘 다 양수
  R14d: prior_12w_foreign + 12w_inst 둘 다 양수
  R14e: prior_4w (foreign OR institution) > 0  (둘 중 하나)
  R14f: prior_12w foreign net > 0 AND R17a (12w+26w momentum)
"""
from __future__ import annotations
import csv, sys, time
from datetime import date, timedelta
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
)
from scripts.grid_R15_R16_momentum_quality import (
    build_features, index_features, filter_cands,
)


def build_flow_index() -> Dict[str, pd.DataFrame]:
    """Per-ticker DataFrame indexed by day with foreign_net + institution_net."""
    print("loading investor_flow from Supabase ...", flush=True)
    t0 = time.time()
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""SELECT ticker, day, foreign_net, institution_net
                       FROM investor_flow ORDER BY ticker, day""")
        rows = cur.fetchall()
    print(f"  loaded {len(rows):,} rows in {time.time()-t0:.1f}s", flush=True)
    df = pd.DataFrame(rows, columns=["ticker", "day", "foreign_net",
                                     "institution_net"])
    df["day"] = pd.to_datetime(df["day"])
    df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce").fillna(0)
    df["institution_net"] = pd.to_numeric(df["institution_net"],
                                          errors="coerce").fillna(0)
    df = df.sort_values(["ticker", "day"])
    out: Dict[str, pd.DataFrame] = {}
    for tic, grp in df.groupby("ticker"):
        out[tic] = grp.set_index("day")[["foreign_net", "institution_net"]]
    print(f"  indexed {len(out):,} tickers", flush=True)
    return out


def cum_flow(idx: Dict[str, pd.DataFrame], ticker: str,
             entry_d: date, days: int) -> tuple:
    df = idx.get(ticker)
    if df is None or df.empty:
        return (None, None)
    end_excl = pd.Timestamp(entry_d)
    start_d = end_excl - pd.Timedelta(days=days)
    window = df.loc[(df.index >= start_d) & (df.index < end_excl)]
    if window.empty:
        return (None, None)
    f = float(window["foreign_net"].sum())
    i = float(window["institution_net"].sum())
    return (f, i)


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

    flow_idx = build_flow_index()
    feat_df = build_features()
    feat_idx = index_features(feat_df)

    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"\nbaseline cands: {len(cands_base):,}", flush=True)

    def filter_flow(cands, days, mode):
        """mode: 'foreign_pos', 'inst_pos', 'both_pos', 'either_pos'."""
        out = []
        for c in cands:
            ed = date.fromisoformat(c["entry_date"])
            f, i = cum_flow(flow_idx, c["ticker"], ed, days)
            if f is None: continue
            if mode == "foreign_pos" and f > 0:
                out.append(c)
            elif mode == "inst_pos" and i is not None and i > 0:
                out.append(c)
            elif mode == "both_pos" and f > 0 and i is not None and i > 0:
                out.append(c)
            elif mode == "either_pos" and (f > 0 or (i is not None and i > 0)):
                out.append(c)
        return out

    pos_key = lambda k: (lambda f: f.get(k) is not None and f[k] > 0)
    mom_pred = lambda f: pos_key("ret_12w")(f) and pos_key("ret_26w")(f)

    VARIANTS = [
        ("R14a_f4w_pos",   lambda: filter_flow(cands_base, 28, "foreign_pos")),
        ("R14b_f12w_pos",  lambda: filter_flow(cands_base, 84, "foreign_pos")),
        ("R14c_fi4w_both", lambda: filter_flow(cands_base, 28, "both_pos")),
        ("R14d_fi12w_both",lambda: filter_flow(cands_base, 84, "both_pos")),
        ("R14e_fi4w_either",lambda: filter_flow(cands_base, 28, "either_pos")),
        ("R14f_f12w_AND_mom", lambda: filter_cands(
            filter_flow(cands_base, 84, "foreign_pos"), feat_idx, mom_pred)),
    ]

    out_rows = []
    # baseline
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

    out_path = ROOT / "data" / "grid_R14_results.csv"
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
