"""SL=5% combined with various trailing-stop and other tweaks.

SL=5% alone gave the best result. Test combinations to see if
anything beats it:
  - SL=5% + TS=10/15/20
  - SL=5% + equity-weighted sizing
  - SL=5% + min-strength 0.85
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

    configs = [
        ("SL=5% (baseline)",      0.05, 0.0, False, 0.0),
        ("SL=5% + TS=10%",        0.05, 0.10, False, 0.0),
        ("SL=5% + TS=15%",        0.05, 0.15, False, 0.0),
        ("SL=5% + TS=20%",        0.05, 0.20, False, 0.0),
        ("SL=5% + equity-weight", 0.05, 0.0, True, 0.0),
        ("SL=5% + min-str 0.85",  0.05, 0.0, False, 0.85),
        ("SL=5% + min-str 0.80",  0.05, 0.0, False, 0.80),
    ]
    for label, sl, ts, ew, mstr in configs:
        cands = P.filter_entry_fires(
            fires, P.DEFAULT_ENTRY_SIGNALS, min_strength=mstr,
        )
        state = P.simulate(
            cands,
            start_date=date(2009, 1, 1), end_date=date(2026, 5, 22),
            initial_cash=10_000_000.0,
            max_positions=20,
            stop_loss_pct=sl,
            trailing_stop_pct=ts,
            equity_weighted_sizing=ew,
        )
        m = compute_full_metrics(state, date(2009, 1, 1), date(2026, 5, 22))
        print(f"=== {label} ===", flush=True)
        print(f"  n_trades      = {len(state.trades)}", flush=True)
        print(f"  total_return  = {m['total_return_pct']:+.2f}%", flush=True)
        print(f"  cagr          = {m['annualised_return_pct']:+.2f}%", flush=True)
        s = m['sharpe']; so = m['sortino']; ca = m['calmar']
        print(f"  sharpe        = {s:.3f}" if s else "  sharpe        = nan", flush=True)
        print(f"  sortino       = {so:.3f}" if so else "  sortino       = nan", flush=True)
        print(f"  calmar        = {ca:.3f}" if ca else "  calmar        = nan", flush=True)
        print(f"  max_dd_mtm    = {m['max_drawdown_mtm_pct']:.2f}%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
