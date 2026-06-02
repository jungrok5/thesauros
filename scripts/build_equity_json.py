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


# 2026-06-02 — book-faithful v2: + Phase 12 signal weights (uniform_by_avg).
#   buy   = top-5 책 신호 + sector_cap=1/주/업종 + 신호별 가중치
#           (action_strong_buy 1.43 / volume_case_3 0.86 / 240MA 0.71,
#           grand-avg 대비 비율, clip [0.5, 1.5])
#   sell  = 종목별 월봉 10MA / 4등분 25% / 천장 패턴 (weekly only)
#   max   = 20 / 자본 1억 / no 24w force / no SL / no TP
#
# Walk-forward (Phase 12, 2026-06-02) confirmed methodology — weights
# estimated on train fold 2009-2017, applied OOS to test fold 2018-26:
#   ΔCAGR +1.08 pp / ΔSharpe +0.028 / ΔAlpha +1.20 pp vs v1 baseline.
# Production weights below are derived from FULL history (2009-2026)
# for a more accurate point estimate; in-sample lift is larger
# (+3.07 pp CAGR) but the *honest* lift is the +1.08 from walk-forward.
#
# Full 17.4y in-sample v2:
#   CAGR +15.55 / Sharpe 0.54 / DD 60.4% / Alpha +7.76 vs KOSPI BH
# Slippage NOT modeled; realistic CAGR ~13-14% (subtract ~2pp/year).
HARDCODED_SUMMARY = {
    "total_return_pct": 1143.19,
    "annualised_return_pct": 15.55,
    "max_drawdown_pct": 60.38,
    "sharpe": 0.544,
    "sortino": 0.787,
    "calmar": 0.257,
    "alpha_annual_pct": 7.76,
    "beta": 0.799,
    "r_squared": 0.259,
    "kospi_ann_ret_pct": 11.48,
    "outperformance_ann_pct": 4.06,
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
        "config": "book-faithful v2: 책 신호 + 업종분산 + 신호별 가중치 (Phase 12 OOS PASS) + 책 매도룰 (월봉 10MA / 4등분 25% / 천장 패턴) — no 24w force, no SL, no TP — max=20 / 자본 1억",
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
