"""Position-sizing comparison.

Two allocation modes during BUY events:
  - "fill"   : alloc = cash / open_slots (current default — first
               buys get more, last buys get less)
  - "equity" : alloc = (cash + sum cost_basis) / max_positions
               (target equal-weight by total equity)

Both modes are simulated by monkey-patching app.backtest.portfolio.simulate
inline via a small wrapper script that re-imports the module. To keep
this as a one-shot, we just CALL the simulate function directly with
a flag instead of via CLI.
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest.metrics import compute_full_metrics

    fires_csv = repo / "data" / "sweep_100_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    cands = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)

    configs = [
        ("baseline (fill)",   {"stop_loss_pct": 0.0, "trailing_stop_pct": 0.0}),
        ("SL=10% only",       {"stop_loss_pct": 0.10, "trailing_stop_pct": 0.0}),
        ("TS=10% only",       {"stop_loss_pct": 0.0, "trailing_stop_pct": 0.10}),
        ("SL=10% + TS=15%",   {"stop_loss_pct": 0.10, "trailing_stop_pct": 0.15}),
    ]
    print(f"# Position-sizing & stop combos (100-ticker 24w, top-5 sigs, max=20)\n",
          flush=True)
    for label, kw in configs:
        state = P.simulate(
            cands,
            start_date=date(2009, 1, 1), end_date=date(2026, 5, 22),
            initial_cash=10_000_000.0,
            max_positions=20,
            **kw,
        )
        m = compute_full_metrics(state, date(2009, 1, 1), date(2026, 5, 22))
        print(f"=== {label} ===", flush=True)
        print(f"  n_trades      = {len(state.trades)}", flush=True)
        print(f"  total_return  = {m['total_return_pct']:+.2f}%", flush=True)
        print(f"  cagr          = {m['annualised_return_pct']:+.2f}%", flush=True)
        print(f"  sharpe        = {m['sharpe']:.3f}" if m['sharpe'] else "  sharpe        = nan", flush=True)
        print(f"  sortino       = {m['sortino']:.3f}" if m['sortino'] else "  sortino       = nan", flush=True)
        print(f"  calmar        = {m['calmar']:.3f}" if m['calmar'] else "  calmar        = nan", flush=True)
        print(f"  max_dd_mtm    = {m['max_drawdown_mtm_pct']:.2f}%", flush=True)
        print(f"  alpha_annual  = {m['alpha_annual_pct']:+.2f}%" if m.get('alpha_annual_pct') is not None else "  alpha_annual  = nan", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
