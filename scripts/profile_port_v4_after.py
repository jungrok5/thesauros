"""Profile portfolio_v4 AFTER cache+refactor.

Runs 2 profiles:
  (1) Cold cache  — first build + backtest
  (2) Warm cache  — pure backtest (cache hit)
"""
from __future__ import annotations

import cProfile
import pstats
import shutil
import sys
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd

from app.book.backtest_portfolio import (
    backtest_portfolio_v4, PortfolioParams,
)
from app.data.pit_db import cursor

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    # Use a different ticker range to avoid colliding with the
    # 497-ticker background job's cache (LIMIT 30 OFFSET 250).
    with cursor() as con:
        tickers = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices "
            "WHERE ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ' "
            "ORDER BY ticker LIMIT 30 OFFSET 250"
        ).fetchall()]

    params = PortfolioParams(
        start=pd.Timestamp("2022-01-01"),
        end=pd.Timestamp("2023-12-31"),
        max_holdings=10,
        book_strict=True,
    )

    # Wipe just these tickers' cache so cold profile is meaningful.
    cache_root = Path("models_store/signal_cache/v1/weekly")
    if cache_root.exists():
        for tk in tickers:
            for suffix in ("", "__bars"):
                p = cache_root / f"{tk.replace('/', '_').replace(':', '_')}{suffix}.parquet"
                if p.exists():
                    p.unlink()

    print(f"\n{'='*80}\nCOLD CACHE profile ({len(tickers)} tickers, 2yr)\n{'='*80}")
    prof_cold = cProfile.Profile()
    prof_cold.enable()
    backtest_portfolio_v4(tickers, params=params, verbose=False,
                          use_cache=True)
    prof_cold.disable()
    s = pstats.Stats(prof_cold).sort_stats("cumulative")
    s.print_stats(20)
    print()
    s.sort_stats("tottime").print_stats(20)

    print(f"\n{'='*80}\nWARM CACHE profile (cache hit)\n{'='*80}")
    prof_warm = cProfile.Profile()
    prof_warm.enable()
    backtest_portfolio_v4(tickers, params=params, verbose=False,
                          use_cache=True)
    prof_warm.disable()
    s = pstats.Stats(prof_warm).sort_stats("cumulative")
    s.print_stats(25)
    print()
    s.sort_stats("tottime").print_stats(20)


if __name__ == "__main__":
    main()
