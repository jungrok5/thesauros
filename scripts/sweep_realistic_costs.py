"""Realistic costs comparison.

Current defaults:
  buy_cost  = 0.015%        (broker only)
  sell_cost = 0.18%         (broker 0.015% + 거래세 0.165%)

Realistic for retail:
  buy_cost  = 0.215%        (broker 0.015% + slip 0.2%)
  sell_cost = 0.395%        (broker 0.015% + 거래세 0.18% + slip 0.2%)

Conservative (high slippage / illiquid):
  buy_cost  = 0.415%        (broker 0.015% + slip 0.4%)
  sell_cost = 0.595%        (broker 0.015% + 거래세 0.18% + slip 0.4%)

양도세 22% only applies above 5억 → most retail = 0. Not included.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


WINNING_CONFIGS = [
    ("SL=3% / max=5",  0.03, 5),
    ("SL=5% / max=8",  0.05, 8),
    ("SL=10% / max=8", 0.10, 8),
]

COST_PROFILES = [
    # (label, buy, sell)
    ("current   (b=0.015%, s=0.18%)",   0.00015, 0.0018),
    ("realistic (b=0.215%, s=0.395%)",  0.00215, 0.00395),
    ("conserva. (b=0.415%, s=0.595%)",  0.00415, 0.00595),
]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest.metrics import compute_full_metrics

    fires_csv = repo / "data" / "sweep_100_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    cands = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)

    print(f"# Realistic costs (24w 100-tic top-5)\n", flush=True)
    print(f"{'config':<20s}  {'cost profile':<35s}  "
          f"{'total':>10s}  {'cagr':>6s}  {'sharpe':>6s}  {'sortino':>7s}",
          flush=True)
    print("-" * 100, flush=True)

    for label, sl, mp in WINNING_CONFIGS:
        for cost_label, b, s in COST_PROFILES:
            state = P.simulate(
                cands, start, end,
                initial_cash=10_000_000.0,
                max_positions=mp,
                stop_loss_pct=sl,
                buy_cost_pct=b,
                sell_cost_pct=s,
            )
            m = compute_full_metrics(state, start, end)
            sh = m['sharpe'] or 0
            so = m['sortino'] or 0
            print(f"{label:<20s}  {cost_label:<35s}  "
                  f"{m['total_return_pct']:>+9.1f}%  "
                  f"{m['annualised_return_pct']:>+5.1f}%  "
                  f"{sh:>6.3f}  {so:>7.3f}", flush=True)
        print(flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
