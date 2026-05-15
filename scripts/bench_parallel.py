"""Benchmark serial vs process-pool cache build (60 tickers, 5yr)."""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    import shutil
    import pandas as pd
    from app.cache.signal_cache import SignalCache, DEFAULT_CACHE_DIR
    from app.book.backtest_portfolio import _load_universe_prices
    from app.data.pit_db import cursor

    with cursor() as con:
        tickers = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices "
            "WHERE ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ' "
            "ORDER BY ticker LIMIT 60"
        ).fetchall()]
    dfs = _load_universe_prices(tickers, pd.Timestamp("2020-01-02"),
                                  pd.Timestamp("2024-12-31"))
    print(f"{len(dfs)} tickers loaded")

    weekly_dir = DEFAULT_CACHE_DIR / "weekly"

    def wipe():
        if weekly_dir.exists():
            for f in weekly_dir.glob("*.parquet"):
                f.unlink()

    print("\n--- Serial ---")
    wipe()
    cache = SignalCache()
    t0 = time.time()
    cache.build_for(list(dfs.keys()), dfs, timeframes=("weekly",),
                     n_jobs=1, verbose=False, force=True)
    t_serial = time.time() - t0
    print(f"  {t_serial:.2f}s")

    print("\n--- ProcessPool (n_jobs=4, use_processes=True) ---")
    wipe()
    cache = SignalCache()
    t0 = time.time()
    cache.build_for(list(dfs.keys()), dfs, timeframes=("weekly",),
                     n_jobs=4, use_processes=True, verbose=False, force=True)
    t_pp4 = time.time() - t0
    print(f"  {t_pp4:.2f}s  → {t_serial/t_pp4:.2f}x")

    print("\n--- ProcessPool (n_jobs=-1, use_processes=True) ---")
    wipe()
    cache = SignalCache()
    t0 = time.time()
    cache.build_for(list(dfs.keys()), dfs, timeframes=("weekly",),
                     n_jobs=-1, use_processes=True, verbose=False, force=True)
    t_pp_all = time.time() - t0
    print(f"  {t_pp_all:.2f}s  → {t_serial/t_pp_all:.2f}x")


if __name__ == "__main__":
    # Required on Windows for multiprocessing
    import multiprocessing as mp
    mp.freeze_support()
    main()
