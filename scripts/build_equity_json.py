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


# 2026-05-29 — honest production (replaces L2):
#   ranking = book_signal_strength only (CAP_WEIGHT=0)
#   diversification = sector_cap=1 per ISO-week per industry
# Phase 9 PIT verification proved the prior L2 cap_q was a look-ahead
# artifact — same-formula CAGR collapsed from +20.65 → +8.07 under
# point-in-time cap. Honest lift over V0 book-only baseline (no cap_q,
# no sector cap):
#   CAGR  14.90% → 16.02%   (+1.12%p, real sector-cap effect)
#   DD    51.46% → 48.24%   (−3.2%p)
#   Alpha  6.66% →  7.20%/y (+0.54%p/y vs KOSPI)
# Slippage NOT modeled; realistic CAGR ~14% (subtract ~2pp/year).
HARDCODED_SUMMARY = {
    "total_return_pct": 1234.87,
    "annualised_return_pct": 16.02,
    "max_drawdown_pct": 48.24,
    "sharpe": 0.725,
    "sortino": 0.924,
    "calmar": 0.332,
    "alpha_annual_pct": 7.20,
    "beta": 0.674,
    "r_squared": 0.417,
    "kospi_ann_ret_pct": 11.48,
    "outperformance_ann_pct": 4.53,
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
        "config": "honest: 책 신호 + 업종분산 (1 종목/주/업종) — no-SL / max=50 / 24w hold / FULL 2701-ticker universe (cap_q 제거: 2026-05-29 PIT look-ahead 검증 후)",
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
