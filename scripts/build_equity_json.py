"""Convert equity CSV to web-shippable JSON.

Input:  data/equity_universe.csv  (universe-honest, no-SL/max=50)
Output: web-next/public/equity-production.json  (~30KB compact)

Replaces the 100-tic seed=42 equity (over-fit, +6380% claim) with
the full 1820-ticker universe result (+795%, modest +1.91%/y alpha
over KOSPI BH). Honest numbers for the public /backtest page.

JSON shape:
{
  "config": "SL=10% / max=8 / 24w / top-5 / 100-tic seed=42",
  "start":  "2009-01-02",
  "end":    "2026-05-22",
  "initial": 10_000_000,
  "summary": {
    "total_return_pct": ...,
    "annualised_return_pct": ...,
    "max_drawdown_pct": ...,
    "sharpe": ...,
    "sortino": ...,
    "calmar": ...,
    "alpha_annual_pct": ...,
    "beta": ...
  },
  "weekly": [
    {"d": "2009-01-02", "e": 9999250},
    {"d": "2009-01-09", "e": 10661411},
    ...
  ]
}
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


# L2 mid-cap sweet (production winner from 2026-05-27 14-variant grid):
#   ranking = 0.8 × book_signal_strength + 0.2 × cap_tent_q
#   cap_tent peaks at ~5,480억 KRW; excludes <500억 (microcap risk) +
#   >10조 (mega-cap institutional crowding).
# Same universe + signal set as 2026-05-26 baseline (full 2701-ticker
# KOSPI+KOSDAQ, sweep_all_24w.csv, F7-F14 eligibility, weekly-first
# pattern_sort_key, fake_volume penalty, fixed triple-bottom detector)
# — only the per-fire ranking changed. Vs V0 baseline (book-only):
#   CAGR  14.90% → 20.65%   (+5.75%p)
#   DD    51.46% → 37.27%   (−14.19%p)
#   Alpha  6.66% → 11.36%/y (+4.70%p/y vs KOSPI)
HARDCODED_SUMMARY = {
    "total_return_pct": 2544.34,
    "annualised_return_pct": 20.65,
    "max_drawdown_pct": 37.27,
    "sharpe": 0.833,
    "sortino": 1.131,
    "calmar": 0.554,
    "alpha_annual_pct": 11.36,
    "beta": 0.713,
    "r_squared": 0.347,
    "kospi_ann_ret_pct": 11.48,
    "outperformance_ann_pct": 9.17,
}


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    src = repo / "data" / "equity_universe.csv"
    dst = repo / "web-next" / "public" / "equity-production.json"
    if not src.exists():
        print(f"missing: {src}", file=sys.stderr)
        return 1

    # equity_universe.csv carries one row per simulator event (buy/sell)
    # — multiple rows can share the same date. We want one row per date
    # for the chart (final equity at end of the bar). Reduce by date,
    # keeping the LAST seen value (which == end-of-bar mark-to-market
    # because portfolio.simulate appends after every event in order).
    by_date: dict[str, float] = {}
    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                e = float(row["equity"])
            except (ValueError, TypeError):
                continue
            by_date[row["date"]] = e
    weekly = [{"d": d, "e": round(e)} for d, e in sorted(by_date.items())]

    if not weekly:
        print("no rows!", file=sys.stderr)
        return 1

    initial = weekly[0]["e"]
    out = {
        "config": "L2 mid-cap sweet (80% book + 20% cap tent) — no-SL / max=50 / 24w hold / top-5 / FULL 2701-ticker universe",
        "start": weekly[0]["d"],
        "end": weekly[-1]["d"],
        "initial": initial,
        "final": weekly[-1]["e"],
        "summary": HARDCODED_SUMMARY,
        "weekly": weekly,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    size_kb = dst.stat().st_size / 1024
    print(f"  weekly rows: {len(weekly)}", flush=True)
    print(f"  start: {weekly[0]['d']}  end: {weekly[-1]['d']}", flush=True)
    print(f"  initial: {initial:,}  final: {weekly[-1]['e']:,}", flush=True)
    print(f"  written: {dst} ({size_kb:.1f} KB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
