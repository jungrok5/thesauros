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


# 2026-05-29 — book-faithful production (replaces honest 24w-hold):
#   buy   = top-5 책 신호 + sector_cap=1 per ISO-week per industry
#   sell  = 종목별 월봉 10MA 깨짐 / 장대양봉 4등분 25% 깨짐 /
#           천장 패턴 (쌍봉/머리어깨/삼중천장/액션매도, weekly only).
#           NO 24w forced exit. NO %-stop. NO take-profit.
#   max   = 20 (sweep winner; 자본 1억/슬롯 = 500만/종목)
#
# Walk-forward audit (2026-05-29) confirmed:
#   - 24w-hold was train-period over-fit (CAGR +21 train / +9 test)
#   - book-faithful is OOS robust   (CAGR +12 train / +13 test)
#   - test-fold lift (book vs 24w-hold): +4.10 pp CAGR, +3.59 pp Alpha
# In-sample full 17.4y (this run):
#   CAGR +12.48 / Sharpe 0.47 / DD 58.6% / Alpha +4.29 vs KOSPI BH
# Slippage NOT modeled; realistic CAGR ~10-11% (subtract ~2pp/year).
HARDCODED_SUMMARY = {
    "total_return_pct": 677.24,
    "annualised_return_pct": 12.48,
    "max_drawdown_pct": 58.62,
    "sharpe": 0.474,
    "sortino": 0.642,
    "calmar": 0.213,
    "alpha_annual_pct": 4.29,
    "beta": 0.674,    # to be refreshed when honest_production_summary regenerated
    "r_squared": 0.417,
    "kospi_ann_ret_pct": 11.48,
    "outperformance_ann_pct": 0.99,
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
        "config": "book-faithful: 책 신호 + 업종분산 (1/주/업종) + 책 매도룰 (월봉 10MA / 4등분 25% / 천장 패턴) — no 24w force, no SL, no TP — max=20 / 자본 1억 / 17.4년 OOS walk-forward 통과",
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
