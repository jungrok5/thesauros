"""Book-faithful backtest — 책 그대로 사고팔기.

Buy:  DEFAULT_ENTRY_SIGNALS (책 5 핵심 신호) + sector_cap=1 per ISO-week
Sell: 종목별 월봉 10MA 깨짐 / 장대양봉 4등분 25% 깨짐 / 천장 패턴 fires.
No 24-week forced exit, no %-stop, no take-profit.

Capital: 1억 initial, allocation = cash / open_slots per BUY.

Output:
  data/book_faithful_summary.json
  data/book_faithful_equity.csv
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import (
    simulate_book_faithful, reset_caches,
)
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


def run(max_positions: int = 20, start=date(2009, 1, 1), end=date(2026, 5, 22)) -> dict:
    print(f"\n── book-faithful (max={max_positions}) ──", flush=True)
    print("loading fires + aux ...", flush=True)
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()

    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    print(f"  cands after sector_cap=1 + book_weight=1.0: {len(cands):,}",
          flush=True)

    exit_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    # 책 정신: 주봉 종가 기준 매매. Daily exit fires (특히
    # action_sell_short) 가 73% 차지하는데 노이즈 수준 → 주봉만 채택.
    # 월봉 청산은 종목별 10MA cross 가 별도 트리거.
    exit_fires = [
        f for f in exit_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    print(f"  exit fires (천장 patterns, weekly only): {len(exit_fires):,}",
          flush=True)

    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=max_positions,
        exit_fires=exit_fires,
    )
    print(f"  sim done: {len(state.trades):,} trades "
          f"in {time.time()-t0:.1f}s", flush=True)

    m = compute_full_metrics(state, start, end)
    print(f"\nmax={max_positions} metrics:")
    print(f"  CAGR              {m['annualised_return_pct']:+.2f}%")
    print(f"  Sharpe            {m['sharpe']:.3f}")
    print(f"  Sortino           {m['sortino']:.3f}")
    print(f"  Calmar            {m['calmar']:.3f}")
    print(f"  Max DD            {m['max_drawdown_mtm_pct']:.2f}%")
    print(f"  Alpha annual      {m.get('alpha_annual_pct'):+.2f}%")
    print(f"  KOSPI ann ret     {m.get('kospi_ann_ret_pct'):+.2f}%")
    print(f"  Outperformance    {m.get('outperformance_ann_pct'):+.2f}%")
    print(f"  Total return      {m['total_return_pct']:+.2f}%")

    return {
        "max_positions": max_positions,
        "n_trades": len(state.trades),
        "n_open_at_end": len(state.positions),
        "metrics": m,
        "state": state,
    }


def write_summary(result: dict) -> None:
    state = result["state"]
    out_json = ROOT / "data" / "book_faithful_summary.json"
    out_eq = ROOT / "data" / "book_faithful_equity.csv"
    print(f"\nwriting {out_json} + {out_eq} ...", flush=True)
    with out_json.open("w", encoding="utf-8") as fp:
        json.dump({
            "config": "book-faithful: 책 신호 + sector_cap=1; 매도 = 월봉 10MA / 4등분 25% / 천장 패턴; 24w-force/SL/TP 없음",
            "max_positions": result["max_positions"],
            "initial_cash": 100_000_000.0,
            "n_trades": result["n_trades"],
            "metrics": result["metrics"],
        }, fp, indent=2, default=str)
    with out_eq.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "equity"])
        for d, e in state.equity_history:
            w.writerow([d.isoformat(), f"{e:.2f}"])


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--sweep", action="store_true",
                   help="sweep max ∈ {10, 20, 30, 50, 100}")
    args = p.parse_args()

    if args.sweep:
        results = []
        for n in [10, 20, 30, 50, 100]:
            r = run(max_positions=n)
            results.append(r)
        print("\n── max sweep ──", flush=True)
        print(f"{'max':>5} {'CAGR':>8} {'Sharpe':>7} {'DD':>7} {'Alpha':>8} {'trades':>7}")
        for r in results:
            m = r["metrics"]
            print(f"{r['max_positions']:>5} "
                  f"{m['annualised_return_pct']:+7.2f}% "
                  f"{m['sharpe']:6.2f} "
                  f"{m['max_drawdown_mtm_pct']:6.1f}% "
                  f"{m.get('alpha_annual_pct'):+7.2f}% "
                  f"{r['n_trades']:>7,}")
        best = max(results, key=lambda r: r["metrics"]["sharpe"])
        print(f"\nbest Sharpe: max={best['max_positions']}", flush=True)
        write_summary(best)
    else:
        r = run(max_positions=args.max)
        write_summary(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
