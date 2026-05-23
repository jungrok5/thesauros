"""Final exhaustive SL=5% sweep: max_positions + active_exit + regime.

Tests whether changing other knobs improves SL=5% beyond +2021%.
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
    from app.backtest.market_regime import kospi_smart_filter

    fires_csv = repo / "data" / "sweep_100_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    cands_default = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    exit_fires_default = P.filter_exit_fires(fires, P.DEFAULT_EXIT_SIGNALS)

    configs = [
        # (label, max_pos, active_exit, regime_smart)
        ("SL=5% / max=20 / baseline",        20, False, False),
        ("SL=5% / max=10",                   10, False, False),
        ("SL=5% / max=30",                   30, False, False),
        ("SL=5% / max=50",                   50, False, False),
        ("SL=5% / max=20 + active-exit",     20, True,  False),
        ("SL=5% / max=20 + regime smart",    20, False, True),
        ("SL=5% / max=20 + active + regime", 20, True,  True),
    ]
    for label, mp, ae, rs in configs:
        regime = kospi_smart_filter(below_threshold_pct=3.0,
                                    require_falling_ma=True) if rs else None
        state = P.simulate(
            cands_default,
            start_date=date(2009, 1, 1), end_date=date(2026, 5, 22),
            initial_cash=10_000_000.0,
            max_positions=mp,
            stop_loss_pct=0.05,
            exit_fires=exit_fires_default if ae else None,
            regime_filter=regime,
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
