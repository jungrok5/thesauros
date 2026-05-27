"""Single L2 mid-cap sweet backtest run — production config, full universe.

Phase 4 grid winner (2026-05-27):
  Ranking = 0.8 × book_signal_strength + 0.2 × cap_tent_q
  where cap_tent_q peaks at ~5,480억 KRW (sqrt of 3000억 × 1조),
  zero below 500억 and above 10조.

Outputs:
  data/equity_universe.csv   — weekly equity curve (overwrites V0 baseline)
  data/l2_production_summary.json  — full metrics

Reads:
  data/sweep_all_24w.csv (315k entry candidates after filter)
  data/market_caps_today.csv (2,242 tickers with cap)
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics

CAP_LOW  = 5e10
CAP_HIGH = 1e13
LOG_LO   = math.log10(CAP_LOW)
LOG_HI   = math.log10(CAP_HIGH)
LOG_PEAK = (math.log10(3e11) + math.log10(1e12)) / 2

BOOK_W = 0.8
CAP_W  = 0.2


def cap_q(mc: float | None) -> float:
    if mc is None or mc <= 0:
        return 0.0
    lc = math.log10(mc)
    if lc <= LOG_LO or lc >= LOG_HI:
        return 0.0
    if lc <= LOG_PEAK:
        return (lc - LOG_LO) / (LOG_PEAK - LOG_LO)
    return (LOG_HI - lc) / (LOG_HI - LOG_PEAK)


def load_cap_map() -> dict[str, float]:
    csv_path = ROOT / "data" / "market_caps_today.csv"
    out: dict[str, float] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            v = (row.get("market_cap_krw") or "").strip()
            if v:
                try:
                    out[row["ticker"]] = float(v)
                except ValueError:
                    pass
    return out


def rerank(fires, cap_map, max_strength):
    out = []
    for f in fires:
        s = float(f.get("strength", 0))
        s_n = s / max_strength if max_strength > 0 else 0
        q = cap_q(cap_map.get(f["ticker"]))
        score = BOOK_W * s_n + CAP_W * q
        new_f = dict(f)
        new_f["strength"] = score
        out.append(new_f)
    return out


def main() -> int:
    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    cap_map = load_cap_map()
    print(f"  cap_map: {len(cap_map):,} tickers with KRW market cap",
          flush=True)

    cands = rerank(fires, cap_map, max_strength)
    start = date(2009, 1, 1)
    end   = date(2026, 5, 22)

    print("running portfolio.simulate (L2 ranking) ...", flush=True)
    t0 = time.time()
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0,
        max_positions=50,
        stop_loss_pct=0.0,
    )
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.0f}s — {len(state.trades):,} trades", flush=True)

    m = compute_full_metrics(state, start, end)
    print(f"\nL2 production metrics:")
    print(f"  CAGR              {m['annualised_return_pct']:+.2f}%")
    print(f"  Sharpe            {m['sharpe']:.3f}")
    print(f"  Sortino           {m['sortino']:.3f}")
    print(f"  Calmar            {m['calmar']:.3f}")
    print(f"  Max DD (MTM)      {m['max_drawdown_mtm_pct']:.2f}%")
    print(f"  Alpha annual      {m.get('alpha_annual_pct'):+.2f}%")
    print(f"  KOSPI ann ret     {m.get('kospi_ann_ret_pct'):+.2f}%")
    print(f"  Outperformance    {m.get('outperformance_ann_pct'):+.2f}%")
    print(f"  Total return      {m['total_return_pct']:+.2f}%")

    # Equity curve (weekly)
    out_eq = ROOT / "data" / "equity_universe.csv"
    print(f"\nwriting equity curve to {out_eq} ...", flush=True)
    with out_eq.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "equity"])
        for d, e in state.equity_history:
            w.writerow([d.isoformat(), f"{e:.2f}"])

    # Summary
    out_json = ROOT / "data" / "l2_production_summary.json"
    print(f"writing summary to {out_json} ...", flush=True)
    with out_json.open("w", encoding="utf-8") as fp:
        json.dump({
            "config": "L2 mid-cap sweet (80% book + 20% cap tent) — no-SL / max=50 / 24w / top-5",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "initial_cash": 10_000_000.0,
            "n_trades": len(state.trades),
            "metrics": m,
        }, fp, indent=2, default=str)

    print("done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
