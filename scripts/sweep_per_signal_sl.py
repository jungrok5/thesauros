"""Per-signal SL impact.

Run portfolio sim using only ONE entry signal at a time, with and
without SL=10%. See which signal benefits most from stop-loss.

Helpful to validate whether the top-5 signal set is still optimal
once SL is on, or if some signals lose value.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


# All single-signal candidates worth testing.
SIGNALS = [
    "volume_case_3", "pattern_forking", "volume_case_7",
    "action_strong_buy", "pattern_ma240_breakout",
    # Also test the rejected ones in case SL revives them
    "action_buy", "pattern_double_bottom", "pattern_triple_bottom",
    "volume_case_12", "pattern_catalyst_candle",
]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest.metrics import compute_full_metrics

    fires_csv = repo / "data" / "sweep_100_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)

    print(f"# Per-signal SL=10% impact (24w 100-tic, max=8, realistic costs)\n",
          flush=True)
    print(f"{'signal':<28s}  {'n_cands':>7s}  "
          f"{'noSL total':>11s}  {'noSL Sor':>9s}  "
          f"{'SL10 total':>11s}  {'SL10 Sor':>9s}  {'delta%':>8s}",
          flush=True)
    print("-" * 100, flush=True)

    for sig in SIGNALS:
        cands = P.filter_entry_fires(fires, [sig])
        if not cands:
            print(f"{sig:<28s}  {'-':>7s}  (no candidates)", flush=True)
            continue
        # No-SL
        st0 = P.simulate(
            cands, start, end,
            initial_cash=10_000_000.0, max_positions=8,
            stop_loss_pct=0.0,
            buy_cost_pct=0.00215, sell_cost_pct=0.00395,
        )
        m0 = compute_full_metrics(st0, start, end)
        # SL=10%
        st1 = P.simulate(
            cands, start, end,
            initial_cash=10_000_000.0, max_positions=8,
            stop_loss_pct=0.10,
            buy_cost_pct=0.00215, sell_cost_pct=0.00395,
        )
        m1 = compute_full_metrics(st1, start, end)

        t0 = m0['total_return_pct']
        t1 = m1['total_return_pct']
        delta = t1 - t0
        so0 = m0['sortino'] or 0
        so1 = m1['sortino'] or 0
        print(f"{sig:<28s}  {len(cands):>7d}  "
              f"{t0:>+10.1f}%  {so0:>9.3f}  "
              f"{t1:>+10.1f}%  {so1:>9.3f}  "
              f"{delta:>+7.1f}%p", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
