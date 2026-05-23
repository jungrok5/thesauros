"""Grid sweep around max=10 / SL=5% sweet spot.

SL ∈ {3, 5, 7, 10} × max_positions ∈ {5, 8, 10, 15} = 16 configs.
Confirms whether (SL=5%, max=10) is the true local maximum.
"""
from __future__ import annotations

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

    SLs = [0.03, 0.05, 0.07, 0.10]
    MAXs = [5, 8, 10, 15]
    print(f"# Grid SL × max_positions (24w, top-5, fires={fires_csv.name})\n", flush=True)
    for sl in SLs:
        for mp in MAXs:
            state = P.simulate(
                cands,
                start_date=date(2009, 1, 1), end_date=date(2026, 5, 22),
                initial_cash=10_000_000.0,
                max_positions=mp,
                stop_loss_pct=sl,
            )
            m = compute_full_metrics(state, date(2009, 1, 1), date(2026, 5, 22))
            print(f"=== SL={int(sl*100)}% / max={mp} ===", flush=True)
            print(f"  total_return  = {m['total_return_pct']:+.2f}%", flush=True)
            print(f"  cagr          = {m['annualised_return_pct']:+.2f}%", flush=True)
            s = m['sharpe']; so = m['sortino']
            print(f"  sharpe        = {s:.3f}" if s else "  sharpe        = nan", flush=True)
            print(f"  sortino       = {so:.3f}" if so else "  sortino       = nan", flush=True)
            print(f"  max_dd_mtm    = {m['max_drawdown_mtm_pct']:.2f}%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
