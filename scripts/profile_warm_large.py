"""Profile warm-cache portfolio_v4 on larger universe."""
from __future__ import annotations

import cProfile
import pstats
import sys
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd
from app.book.backtest_portfolio import backtest_portfolio_v4, PortfolioParams
from app.data.pit_db import cursor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    with cursor() as con:
        tickers = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices "
            "WHERE ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ' "
            "ORDER BY ticker LIMIT 100"
        ).fetchall()]

    params = PortfolioParams(
        start=pd.Timestamp("2020-01-02"),
        end=pd.Timestamp("2024-12-31"),
        max_holdings=30, book_strict=True,
    )

    # Warm-up cache once
    backtest_portfolio_v4(tickers, params=params, verbose=False, use_cache=True)

    print(f"\n{'='*80}\nWARM profile (100 tickers, 5yr)\n{'='*80}")
    prof = cProfile.Profile()
    prof.enable()
    backtest_portfolio_v4(tickers, params=params, verbose=False, use_cache=True)
    prof.disable()
    s = pstats.Stats(prof).sort_stats("cumulative")
    s.print_stats(25)
    print()
    s.sort_stats("tottime").print_stats(20)


if __name__ == "__main__":
    main()
