"""Walk-forward OOS — overfitting check.

Split 2009-2026 (17 yr) into 3 folds:
  F1: train 2009-2014, test 2014-2018
  F2: train 2014-2018, test 2018-2022
  F3: train 2018-2022, test 2022-2026

For each fold:
  1. Run all 16 SL × max configs on TRAIN period — pick best by Sortino.
  2. Apply the SAME winning config to TEST period — record metrics.

If the same config wins across all folds AND test-period returns are
positive, the strategy is robust (not overfit to the 17-year window).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


SLs = [0.03, 0.05, 0.07, 0.10]
MAXs = [5, 8, 10, 15]

FOLDS = [
    ("F1", date(2009, 1, 1),  date(2014, 12, 31), date(2015, 1, 1), date(2018, 12, 31)),
    ("F2", date(2014, 1, 1),  date(2018, 12, 31), date(2019, 1, 1), date(2022, 12, 31)),
    ("F3", date(2018, 1, 1),  date(2022, 12, 31), date(2023, 1, 1), date(2026, 5, 22)),
]


def run_one(P, M, cands, sl, mp, start, end):
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0, max_positions=mp,
        stop_loss_pct=sl,
    )
    m = M.compute_full_metrics(state, start, end)
    return m


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest import metrics as M

    fires_csv = repo / "data" / "sweep_100_24w.csv"
    fires = P.load_fires_csv(fires_csv)
    cands_all = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)

    for name, tr_s, tr_e, te_s, te_e in FOLDS:
        print(f"\n## {name}: train {tr_s}→{tr_e}, test {te_s}→{te_e}",
              flush=True)

        # TRAIN: find best (SL, max) by Sortino
        best_label = None
        best_sortino = -1e9
        best_train_metrics = None
        for sl in SLs:
            for mp in MAXs:
                m = run_one(P, M, cands_all, sl, mp, tr_s, tr_e)
                so = m['sortino'] or -1
                if so > best_sortino:
                    best_sortino = so
                    best_label = (sl, mp)
                    best_train_metrics = m

        sl, mp = best_label
        print(f"  TRAIN winner: SL={int(sl*100)}% / max={mp} → "
              f"total={best_train_metrics['total_return_pct']:+.1f}%, "
              f"sortino={best_sortino:.3f}", flush=True)

        # TEST: apply that config to test period
        m_test = run_one(P, M, cands_all, sl, mp, te_s, te_e)
        sh = m_test['sharpe'] or 0
        so = m_test['sortino'] or 0
        print(f"  TEST  result: total={m_test['total_return_pct']:+.1f}%, "
              f"cagr={m_test['annualised_return_pct']:+.1f}%, "
              f"sharpe={sh:.3f}, sortino={so:.3f}, "
              f"DD={m_test['max_drawdown_mtm_pct']:.1f}%",
              flush=True)

    print("\n# Robustness summary\n", flush=True)
    print("If TRAIN winner = consistent (e.g., always SL=10/max=8) AND "
          "TEST returns positive → strategy is robust.", flush=True)
    print("If TRAIN winners differ wildly → param-tuned for history → "
          "overfit risk.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
