"""R12 — US-KR lead-lag factor on v1.1 universe.

Hypothesis: KR industry baskets (Hynix, Samsung, etc.) lag their US
counterparts (MU, NVDA, TSM, etc.) by 1-2 weeks. Using US weekly
momentum as a confirmation gate or score boost should add real
information to book-only ranking.

Mapping (US → KR ticker basket):
  MU, NVDA, AMD, INTC, MRVL → 000660.KS (Hynix), 042700.KS (한미반도체)
  AAPL, TSM, ASML, AVGO     → 005930.KS (Samsung), 000660.KS (Hynix)
  TSLA                       → 373220.KS (LG엔솔), 006400.KS (삼성SDI),
                                096770.KS (SK이노)
  MSFT                       → 035420.KS (NAVER)
  GOOGL                      → 035720.KS (Kakao)
  QCOM                       → 005930.KS

For each KR fire at entry_date t, we compute the mean weekly return of
the mapped US tickers over the prior week (t-1 to t). If positive → US
basket "leading up" → boost or pass; if negative → drop or downweight.

Variants:
  R12a — drop fires where US lead < 0 (binary gate, threshold 0)
  R12b — drop where US lead < +1%
  R12c — drop where US lead < +3%
  R12d — score boost: rescore = book + us_w * tanh(us_lead × 10)
  R12e — pass if ANY mapped US ticker > +5% (loose)

Output: data/grid_R12_us_leadlag_results.csv
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import math
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


US_KR_LEAD: Dict[str, List[str]] = {
    "MU":    ["000660.KS", "042700.KS"],
    "NVDA":  ["000660.KS", "042700.KS"],
    "AMD":   ["000660.KS"],
    "INTC":  ["005930.KS", "000660.KS"],
    "MRVL":  ["000660.KS"],
    "AAPL":  ["005930.KS", "000660.KS"],
    "TSM":   ["005930.KS"],
    "ASML":  ["005930.KS", "000660.KS"],
    "AVGO":  ["005930.KS", "000660.KS"],
    "TSLA":  ["373220.KS", "006400.KS", "096770.KS"],
    "MSFT":  ["035420.KS"],
    "GOOGL": ["035720.KS"],
    "QCOM":  ["005930.KS"],
}

# Invert: KR ticker → list of US lead tickers
KR_US_LEAD: Dict[str, List[str]] = {}
for us, kr_list in US_KR_LEAD.items():
    for kr in kr_list:
        KR_US_LEAD.setdefault(kr, []).append(us)


def load_us_weekly() -> Dict[str, pd.DataFrame]:
    """Load US weekly bars per ticker into dict."""
    con = duckdb.connect(str(ROOT / "data" / "us_leadlag.duckdb"),
                         read_only=True)
    rows = con.sql(
        "SELECT ticker, bar_date, close FROM bars "
        "WHERE granularity='W' ORDER BY ticker, bar_date"
    ).fetchall()
    con.close()
    out: Dict[str, pd.DataFrame] = {}
    df_all = pd.DataFrame(rows, columns=["ticker", "bar_date", "close"])
    df_all["bar_date"] = pd.to_datetime(df_all["bar_date"])
    df_all = df_all.sort_values(["ticker", "bar_date"])
    df_all["ret_1w"] = df_all.groupby("ticker")["close"].pct_change()
    for tic, grp in df_all.groupby("ticker"):
        out[tic] = grp.set_index("bar_date")
    return out


def us_lead_return_for(
    kr_ticker: str, entry_date: date,
    us_data: Dict[str, pd.DataFrame],
) -> Optional[float]:
    """Mean of prior-week returns across mapped US tickers.
    Returns None if no mapping or no aligned data."""
    us_list = KR_US_LEAD.get(kr_ticker)
    if not us_list:
        return None
    target = pd.Timestamp(entry_date)
    rets = []
    for us in us_list:
        df = us_data.get(us)
        if df is None or df.empty:
            continue
        # Find most-recent weekly bar <= target
        slice_df = df[df.index <= target]
        if len(slice_df) < 2:
            continue
        last_ret = slice_df["ret_1w"].iloc[-1]
        if pd.isna(last_ret):
            continue
        rets.append(float(last_ret))
    if not rets:
        return None
    return sum(rets) / len(rets)


def filter_by_us_lead(
    cands: List[Dict[str, Any]],
    us_data: Dict[str, pd.DataFrame],
    threshold: float,
    require_mapping: bool = True,
) -> List[Dict[str, Any]]:
    """Keep candidates whose US lead avg return >= threshold.

    If require_mapping=False, candidates without a US mapping pass
    through unfiltered (so the gate only activates on mapped tickers).
    """
    out = []
    n_mapped = 0
    n_pass = 0
    for c in cands:
        entry_d = date.fromisoformat(c["entry_date"])
        us_ret = us_lead_return_for(c["ticker"], entry_d, us_data)
        if us_ret is None:
            if not require_mapping:
                out.append(c)
            continue
        n_mapped += 1
        if us_ret >= threshold:
            out.append(c)
            n_pass += 1
    print(f"    [us_lead threshold={threshold:+.2%}] "
          f"mapped={n_mapped} pass={n_pass} "
          f"({n_pass/max(1,n_mapped)*100:.1f}% of mapped)", flush=True)
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

    print("loading US weekly bars ...", flush=True)
    us_data = load_us_weekly()
    print(f"  US tickers loaded: {len(us_data)}", flush=True)
    kr_with_mapping = set(KR_US_LEAD.keys())
    n_fires_mapped = sum(1 for f in fires if f["ticker"] in kr_with_mapping)
    print(f"  KR fires with US mapping: {n_fires_mapped:,} / {len(fires):,} "
          f"({n_fires_mapped/len(fires)*100:.1f}%)", flush=True)

    # baseline first (book-only sector_cap=1, no us filter — full universe)
    cands_base = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"\n[baseline] book-only sector_cap=1 → {len(cands_base):,} cands",
          flush=True)
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands_base, start, end,
        initial_cash=100_000_000.0, max_positions=20,
        exit_fires=exit_fires, delisting_dates=delisting_dates,
    )
    m_base = compute_full_metrics(state, start, end)
    print(f"  CAGR={m_base['annualised_return_pct']:+.2f} "
          f"Alpha={m_base.get('alpha_annual_pct'):+.2f} "
          f"Outperf={m_base.get('outperformance_ann_pct'):+.2f} "
          f"({time.time()-t0:.0f}s)", flush=True)

    out_rows = [{
        "variant": "book_only_baseline",
        "n_cands": len(cands_base),
        "n_trades": len(state.trades),
        "cagr": m_base["annualised_return_pct"],
        "sharpe": m_base["sharpe"],
        "alpha_ann": m_base.get("alpha_annual_pct"),
        "outperf_ann": m_base.get("outperformance_ann_pct"),
        "dd_pct": m_base["max_drawdown_mtm_pct"],
    }]

    VARIANTS = [
        ("R12a_us_gate_0", 0.0,  True),
        ("R12b_us_gate_1pct", 0.01, True),
        ("R12c_us_gate_3pct", 0.03, True),
        ("R12d_us_gate_0_strict", 0.0, True),
        # require_mapping=False — apply gate only to mapped tickers,
        # let unmapped pass unconditionally
        ("R12e_us_gate_0_pass_unmapped", 0.0, False),
        ("R12f_us_gate_1pct_pass_unmapped", 0.01, False),
    ]

    for i, (key, thr, req_map) in enumerate(VARIANTS, start=1):
        print(f"\n[{i}/{len(VARIANTS)}] {key}", flush=True)
        cands = filter_by_us_lead(cands_base, us_data, thr, require_mapping=req_map)
        print(f"  cands after gate: {len(cands):,}", flush=True)
        if not cands:
            print(f"  → 0 cands, skip", flush=True)
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
            "n_cands": len(cands),
            "n_trades": len(state.trades),
            "cagr": m["annualised_return_pct"],
            "sharpe": m["sharpe"],
            "alpha_ann": m.get("alpha_annual_pct"),
            "outperf_ann": m.get("outperformance_ann_pct"),
            "dd_pct": m["max_drawdown_mtm_pct"],
        })

    out_path = ROOT / "data" / "grid_R12_us_leadlag_results.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n→ wrote {out_path}", flush=True)

    out_rows.sort(key=lambda r: (r["alpha_ann"] or -99), reverse=True)
    print("\n── Leaderboard ──", flush=True)
    for r in out_rows:
        print(f"  {r['variant']:>35} CAGR {r['cagr']:+6.2f} "
              f"Sharpe {r['sharpe']:.3f} Alpha {r['alpha_ann']:+6.2f} "
              f"Outperf {r['outperf_ann']:+6.2f} trades {r['n_trades']:>5}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
