"""Production winning config on FULL universe — max sweep.

100-tic seed=42 = +6380% but universe = +58.7% — huge gap. Test
different max_positions to find universe-optimal slot count.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


CONFIGS = [
    # (label, max_positions, stop_loss_pct)
    ("SL=10% / max=8",   8,  0.10),
    ("SL=10% / max=20",  20, 0.10),
    ("SL=10% / max=50",  50, 0.10),
    ("SL=10% / max=100", 100, 0.10),
    ("no-SL / max=20",   20, 0.0),
    ("no-SL / max=50",   50, 0.0),
    ("SL=5% / max=20",   20, 0.05),
    ("SL=5% / max=50",   50, 0.05),
]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest.metrics import compute_full_metrics

    fires_csv = repo / "data" / "sweep_all_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    cands = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    print(f"# universe 24w: {len(fires):,} fires → {len(cands):,} entry cands\n",
          flush=True)
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)

    for label, mp, sl in CONFIGS:
        state = P.simulate(
            cands, start, end,
            initial_cash=10_000_000.0,
            max_positions=mp,
            stop_loss_pct=sl,
        )
        m = compute_full_metrics(state, start, end)
        sh = m['sharpe'] or 0
        so = m['sortino'] or 0
        ca = m['calmar'] or 0
        print(f"{label:<25s}  n_tr={len(state.trades):>5}  "
              f"total={m['total_return_pct']:>+8.1f}%  "
              f"cagr={m['annualised_return_pct']:>+5.1f}%/y  "
              f"Sh={sh:.2f}  So={so:.2f}  Ca={ca:.2f}  "
              f"DD={m['max_drawdown_mtm_pct']:.1f}%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
