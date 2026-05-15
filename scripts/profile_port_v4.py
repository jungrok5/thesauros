"""Profile backtest_portfolio_v4 — 어디가 진짜 병목인지 cProfile 로 확인."""
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
    # Sample: 30 tickers, 2 years (대표 부하)
    with cursor() as con:
        tickers = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices "
            "WHERE ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ' "
            "ORDER BY ticker LIMIT 30"
        ).fetchall()]

    params = PortfolioParams(
        start=pd.Timestamp("2022-01-01"),
        end=pd.Timestamp("2023-12-31"),
        max_holdings=10,
        book_strict=True,
    )

    profiler = cProfile.Profile()
    profiler.enable()
    backtest_portfolio_v4(tickers, params=params, verbose=False)
    profiler.disable()

    stats = pstats.Stats(profiler).sort_stats("cumulative")
    print("=" * 80)
    print("TOP 30 cumulative time:")
    print("=" * 80)
    stats.print_stats(30)
    print()
    print("=" * 80)
    print("TOP 30 internal time (tottime):")
    print("=" * 80)
    stats.sort_stats("tottime").print_stats(30)


if __name__ == "__main__":
    main()
