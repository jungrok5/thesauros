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


# 2026-06-03 — v1.1 survivorship-corrected production locked baseline.
# Universe = 3,465 ticker (KR 2,599 active + 883 FDR-ingested delisted).
# Simulator auto-closes positions on delisted_at to avoid slot-occupation
# bias. Prior v1 (CAGR 12.48 / Outperf +0.99) was inflated by ~1.3 pp from
# survivorship bias — corrected here.
#
# 2026-06-02/03 사이클: v1.1 위에서 24 ranking-factor 시도 (R1-R20)
# 모두 5-gate 룰 (PIT/4-fold ≥3/4/outlier-excl/bootstrap p<0.05/signal
# <70%) 미달 → REJECT. v1.1 가 honest production baseline.
#
# v1.1 spec (locked):
#   buy   = top-5 책 신호 + sector_cap=1/주/업종
#   sell  = 종목별 월봉 10MA / 4등분 25% / 천장 패턴 (weekly only)
#         + 폐지일 자동 청산 (FDR delisted_at)
#   max   = 20 / 자본 1억 / no 24w force / no SL / no TP
#
# Full 17.4y in-sample v1.1:
#   CAGR +11.19 / Sharpe 0.43 / DD 63.1% / Alpha +3.36 vs KOSPI BH
#   Outperf -0.29 pp/y (KOSPI BH 와 동률, β-corrected alpha 만 양수)
#   β=0.61 R²=0.29 → KOSPI 변동성의 61% 만 부담
# Slippage NOT modeled; realistic CAGR ~9-10% (subtract ~1-2pp/year).
HARDCODED_SUMMARY = {
    "total_return_pct": 536.55,
    "annualised_return_pct": 11.19,
    "max_drawdown_pct": 63.08,
    "sharpe": 0.434,
    "sortino": 0.611,
    "calmar": 0.177,
    "alpha_annual_pct": 3.36,
    "beta": 0.608,
    "r_squared": 0.290,
    "kospi_ann_ret_pct": 11.48,
    "outperformance_ann_pct": -0.29,
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
        "config": "book-faithful v1.1 (survivorship-corrected locked baseline; 24 ranking-factor 시도 모두 5-gate REJECT): 책 신호 + 업종분산 + 책 매도룰 (월봉 10MA / 4등분 25% / 천장 패턴) + 폐지일 자동청산 — no 24w force, no SL, no TP — max=20 / 자본 1억 / universe 3,465 (active 2,599 + delisted 866)",
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
