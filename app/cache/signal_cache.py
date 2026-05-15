"""Signal cache — precompute detect_signals_at for ticker × timeframe × all bars.

Cache layout:
  models_store/signal_cache/{version}/{timeframe}/{ticker}.parquet

Each parquet has one row per (date × signal):
  ticker, date, kind, source, confidence, detail,
  trend_type, bearish_alignment, volume_zone, close, ma_10, ma_240

Usage:
    cache = SignalCache()
    cache.build_for(['AAPL', 'MSFT'], timeframe='weekly')
    ss = cache.get_signal_set('AAPL', 'weekly', pd.Timestamp('2024-06-21'))
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.book.signals import detect_signals_at, Signal, SignalSet
from app.book.trend import resample_to_period


# ---------------------------------------------------------------------------
# Code-hash automatic cache invalidation
# ---------------------------------------------------------------------------
# Files whose source-code changes should invalidate the cache. Any edit
# to one of these (even a comment) will cause a fresh cache directory.
_SIGNAL_CODE_FILES = [
    "app/book/signals.py",
    "app/book/patterns.py",
    "app/book/reversals.py",
    "app/book/volume.py",
    "app/book/trend.py",
    "app/book/candles.py",
    "app/book/_swings.py",
]


def _compute_signal_code_hash() -> str:
    """Hash the contents of all signal-affecting modules. 10-char prefix."""
    h = hashlib.sha256()
    for rel in _SIGNAL_CODE_FILES:
        p = Path(rel)
        if p.exists():
            h.update(p.read_bytes())
        else:
            h.update(rel.encode())  # missing file marker
    return h.hexdigest()[:10]


# Schema version (bump for changes to cache LAYOUT, not signal logic)
SIGNAL_CACHE_SCHEMA = "s2"

SIGNAL_CACHE_VERSION = f"{SIGNAL_CACHE_SCHEMA}_{_compute_signal_code_hash()}"

CACHE_ROOT = Path("models_store/signal_cache")
DEFAULT_CACHE_DIR = CACHE_ROOT / SIGNAL_CACHE_VERSION


# ---------------------------------------------------------------------------
# Top-level worker for ProcessPool — must be picklable, no closures
# ---------------------------------------------------------------------------
def _process_worker(args):
    """Build cache for one ticker. Runs in a separate process.

    args = (ticker, cache_dir_str, tf, force)
    Each worker independently:
      - opens its own DuckDB connection
      - loads OHLCV for one ticker
      - builds/updates cache
    """
    ticker, cache_dir_str, tf, force = args
    try:
        from pathlib import Path
        import pandas as pd
        from app.cache.signal_cache import SignalCache
        from app.data.pit_db import cursor

        with cursor() as con:
            df = con.execute(
                "SELECT date, open, high, low, close, volume FROM prices "
                "WHERE ticker = ? ORDER BY date",
                [ticker],
            ).df()
        if df.empty or len(df) < 250:
            return (ticker, "skip", 0)
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)

        cache = SignalCache(Path(cache_dir_str))
        if force:
            sig_df, bars_df = cache._compute_one(ticker, tf, df)
            cache._path(ticker, tf).parent.mkdir(parents=True, exist_ok=True)
            if not sig_df.empty:
                sig_df.to_parquet(cache._path(ticker, tf), index=False)
            if not bars_df.empty:
                bars_df.to_parquet(cache._bars_path(ticker, tf), index=False)
            return (ticker, "full", len(sig_df))
        status, n = cache._incremental_update(ticker, tf, df)
        return (ticker, status, n)
    except Exception as e:
        return (ticker, f"error:{e}", 0)


def cleanup_stale_cache_dirs(keep: int = 2, verbose: bool = True) -> int:
    """Remove old cache directories that don't match the current code hash.

    Keeps the `keep` most-recently-modified dirs (in case you bounce between
    branches). Returns number of dirs deleted.
    """
    if not CACHE_ROOT.exists():
        return 0
    dirs = [d for d in CACHE_ROOT.iterdir() if d.is_dir()]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    to_delete = [d for d in dirs[keep:]
                  if d.name != SIGNAL_CACHE_VERSION]
    for d in to_delete:
        if verbose:
            print(f"[signal-cache] removing stale dir: {d.name}")
        shutil.rmtree(d, ignore_errors=True)
    return len(to_delete)


class SignalCache:
    """On-disk parquet cache of detect_signals_at results."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # in-memory lookup: (ticker, tf) -> dict[date -> SignalSet]
        self._mem: Dict[Tuple[str, str], Dict[pd.Timestamp, SignalSet]] = {}
        # bar metadata: (ticker, tf) -> DataFrame with date/close/ma_10/ma_240
        self._bars: Dict[Tuple[str, str], pd.DataFrame] = {}

    def _path(self, ticker: str, tf: str) -> Path:
        safe = ticker.replace("/", "_").replace(":", "_")
        return self.cache_dir / tf / f"{safe}.parquet"

    def _bars_path(self, ticker: str, tf: str) -> Path:
        safe = ticker.replace("/", "_").replace(":", "_")
        return self.cache_dir / tf / f"{safe}__bars.parquet"

    @staticmethod
    def _resample(daily_df: pd.DataFrame, tf: str) -> pd.DataFrame:
        if tf == "daily":
            df = daily_df.copy()
        elif tf == "weekly":
            df = resample_to_period(daily_df, "W").reset_index()
        elif tf == "monthly":
            df = resample_to_period(daily_df, "M").reset_index()
        else:
            raise ValueError(f"unknown tf: {tf}")
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})
        df["date"] = pd.to_datetime(df["date"])
        return df.reset_index(drop=True)

    def _compute_one(self, ticker: str, tf: str,
                     daily_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Compute all signals + bar metadata for ticker/tf. Returns (signals_df, bars_df)."""
        df = self._resample(daily_df, tf)
        if len(df) < 70:
            return pd.DataFrame(), pd.DataFrame()

        # add MAs once to bars_df
        from app.book.trend import add_moving_averages
        bars_df = add_moving_averages(df, [10, 240]).copy()
        bars_df = bars_df[["date", "open", "high", "low", "close", "volume",
                            "ma_10", "ma_240"]].copy()
        bars_df["ticker"] = ticker

        rows = []
        for i in range(len(df)):
            try:
                ss = detect_signals_at(df, i)
            except Exception:
                continue
            if not ss.signals and not ss.trend_type and not ss.bearish_alignment:
                continue
            bar_date = pd.to_datetime(df["date"].iloc[i])
            close = float(df["close"].iloc[i])
            base = {
                "ticker": ticker, "date": bar_date,
                "close": close,
                "trend_type": ss.trend_type or "unknown",
                "bearish_alignment": bool(ss.bearish_alignment),
                "volume_zone": ss.volume_zone or "neutral",
                "ma_10": ss.ma_10, "ma_240": ss.ma_240,
            }
            if ss.signals:
                for sig in ss.signals:
                    rows.append({**base,
                                  "kind": sig.kind, "source": sig.source,
                                  "confidence": float(sig.confidence),
                                  "detail": sig.detail or ""})
            else:
                # Save context-only row (no signals but trend/alignment data)
                rows.append({**base, "kind": "_NONE", "source": "",
                              "confidence": 0.0, "detail": ""})
        sig_df = pd.DataFrame(rows)
        # Only string→category (parquet dictionary encoding) — lossless
        # compression. No float downcast: even tiny precision loss in
        # `confidence` can flip threshold comparisons.
        if not sig_df.empty:
            for col in ("kind", "source", "trend_type", "volume_zone"):
                if col in sig_df.columns:
                    sig_df[col] = sig_df[col].astype("category")
        return sig_df, bars_df

    def _incremental_update(self, ticker: str, tf: str,
                             daily_df: pd.DataFrame) -> Tuple[str, int]:
        """If cache exists, append signals only for new bars after the last
        cached date. Returns (status, n_new_signal_rows).
        Status: 'full' / 'incremental' / 'uptodate' / 'empty'."""
        path = self._path(ticker, tf)
        bars_path = self._bars_path(ticker, tf)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists() or not bars_path.exists():
            sig_df, bars_df = self._compute_one(ticker, tf, daily_df)
            if sig_df.empty:
                return ("empty", 0)
            sig_df.to_parquet(path, index=False)
            bars_df.to_parquet(bars_path, index=False)
            return ("full", len(sig_df))

        # Cache exists — check if new bars to add
        existing_bars = pd.read_parquet(bars_path)
        existing_bars["date"] = pd.to_datetime(existing_bars["date"])
        last_cached = existing_bars["date"].max()

        df = self._resample(daily_df, tf)
        new_mask = df["date"] > last_cached
        if not new_mask.any():
            return ("uptodate", 0)

        # Need to recompute signals for new bars (with full lookback window)
        from app.book.trend import add_moving_averages
        bars_df = add_moving_averages(df, [10, 240])[
            ["date", "open", "high", "low", "close", "volume", "ma_10", "ma_240"]
        ].copy()
        bars_df["ticker"] = ticker

        new_indices = df.index[new_mask].tolist()
        new_rows = []
        for i in new_indices:
            try:
                ss = detect_signals_at(df, i)
            except Exception:
                continue
            bar_date = pd.to_datetime(df["date"].iloc[i])
            close = float(df["close"].iloc[i])
            base = {
                "ticker": ticker, "date": bar_date, "close": close,
                "trend_type": ss.trend_type or "unknown",
                "bearish_alignment": bool(ss.bearish_alignment),
                "volume_zone": ss.volume_zone or "neutral",
                "ma_10": ss.ma_10, "ma_240": ss.ma_240,
            }
            if ss.signals:
                for sig in ss.signals:
                    new_rows.append({**base, "kind": sig.kind,
                                      "source": sig.source,
                                      "confidence": float(sig.confidence),
                                      "detail": sig.detail or ""})
            else:
                new_rows.append({**base, "kind": "_NONE", "source": "",
                                  "confidence": 0.0, "detail": ""})

        if not new_rows:
            return ("uptodate", 0)

        # Append: read existing signals + concat with new
        existing_signals = pd.read_parquet(path)
        new_sig_df = pd.DataFrame(new_rows)
        # Match dtypes (category for strings)
        for col in ("kind", "source", "trend_type", "volume_zone"):
            if col in new_sig_df.columns and col in existing_signals.columns:
                if existing_signals[col].dtype.name == "category":
                    new_sig_df[col] = new_sig_df[col].astype(
                        pd.CategoricalDtype(
                            categories=existing_signals[col].cat.categories.union(
                                new_sig_df[col].unique()
                            )
                        )
                    )
                    existing_signals[col] = existing_signals[col].astype(
                        new_sig_df[col].dtype
                    )
        combined = pd.concat([existing_signals, new_sig_df],
                              ignore_index=True)
        combined.to_parquet(path, index=False)
        bars_df.to_parquet(bars_path, index=False)
        return ("incremental", len(new_rows))

    def build_for(self, tickers: Iterable[str],
                  daily_dfs: Dict[str, pd.DataFrame],
                  timeframes: Iterable[str] = ("daily", "weekly", "monthly"),
                  force: bool = False,
                  incremental: bool = True,
                  verbose: bool = True,
                  n_jobs: int = 1,
                  use_processes: bool = False) -> Dict[str, int]:
        """Build cache for given tickers / timeframes.

        daily_dfs: {ticker -> daily OHLCV df}
        force: if True, rebuild from scratch even if cache exists
        incremental: if True (default), only append signals for new bars
            when cache already exists. Set False for raw cache-miss build.
        n_jobs: number of parallel workers (1 = sequential)
        Returns dict {tf: n_built}.
        """
        tickers = [tk for tk in tickers if tk in daily_dfs]
        result: Dict[str, int] = {}
        for tf in timeframes:
            (self.cache_dir / tf).mkdir(parents=True, exist_ok=True)
            todo = []
            for tk in tickers:
                if force:
                    todo.append(tk)
                elif self._path(tk, tf).exists() and self._bars_path(tk, tf).exists():
                    if incremental:
                        todo.append(tk)  # check for incremental update
                    # else: skip already-cached tickers
                else:
                    todo.append(tk)  # not cached, must build
            if not todo:
                result[tf] = 0
                if verbose:
                    print(f"  [{tf}] cache hit: 0 to build, {len(tickers)} already cached")
                continue
            if verbose:
                print(f"  [{tf}] processing {len(todo)} tickers (n_jobs={n_jobs}, incremental={incremental}) …")

            def _work(tk):
                if incremental and not force:
                    status, n = self._incremental_update(tk, tf, daily_dfs[tk])
                    return tk, n, status
                sig_df, bars_df = self._compute_one(tk, tf, daily_dfs[tk])
                # Ensure dir exists (multithreaded-safe)
                self._path(tk, tf).parent.mkdir(parents=True, exist_ok=True)
                if not sig_df.empty:
                    sig_df.to_parquet(self._path(tk, tf), index=False)
                if not bars_df.empty:
                    bars_df.to_parquet(self._bars_path(tk, tf), index=False)
                return tk, len(sig_df), "full"

            if use_processes and n_jobs != 1:
                # Process pool: each worker has own DuckDB + ticker data load
                from concurrent.futures import ProcessPoolExecutor, as_completed
                import os
                workers = n_jobs if n_jobs > 0 else max(os.cpu_count() - 1, 1)
                args = [(tk, str(self.cache_dir), tf, force) for tk in todo]
                done = 0
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    futures = {ex.submit(_process_worker, a): a[0] for a in args}
                    for fut in as_completed(futures):
                        done += 1
                        if verbose and done % 50 == 0:
                            print(f"    {done}/{len(todo)} done")
            elif n_jobs == 1 or n_jobs == 0:
                for j, tk in enumerate(todo, 1):
                    _work(tk)
                    if verbose and j % 50 == 0:
                        print(f"    {j}/{len(todo)} {tk}")
            else:
                try:
                    from joblib import Parallel, delayed
                    # threading backend: pandas/numpy ops release GIL so
                    # this is much faster than 'loky' on Windows
                    # (spawn overhead avoided; df copies avoided)
                    Parallel(n_jobs=n_jobs, backend="threading",
                              verbose=(10 if verbose else 0))(
                        delayed(_work)(tk) for tk in todo
                    )
                except ImportError:
                    for tk in todo:
                        _work(tk)
            result[tf] = len(todo)
            if verbose:
                print(f"  [{tf}] built {len(todo)} ticker caches.")
        return result

    def _load_into_mem(self, ticker: str, tf: str):
        key = (ticker, tf)
        if key in self._mem:
            return
        path = self._path(ticker, tf)
        bars_path = self._bars_path(ticker, tf)
        if not path.exists() or not bars_path.exists():
            self._mem[key] = {}
            self._bars[key] = pd.DataFrame()
            return

        df = pd.read_parquet(path)
        bars = pd.read_parquet(bars_path)
        bars["date"] = pd.to_datetime(bars["date"])
        self._bars[key] = bars.set_index("date").sort_index()

        # ---- Vectorized parquet → dict-of-SignalSet ----
        # Pull all columns as numpy arrays once; avoid per-row pandas access.
        dates = pd.to_datetime(df["date"]).to_numpy()
        closes = df["close"].to_numpy()
        kinds = df["kind"].to_numpy()
        sources = df["source"].to_numpy()
        confs = df["confidence"].to_numpy()
        details = df["detail"].to_numpy() if "detail" in df.columns else np.array([""] * len(df))
        trend_arr = df["trend_type"].to_numpy() if "trend_type" in df.columns else np.array(["unknown"] * len(df))
        bear_arr = df["bearish_alignment"].to_numpy() if "bearish_alignment" in df.columns else np.array([False] * len(df))
        vz_arr = df["volume_zone"].to_numpy() if "volume_zone" in df.columns else np.array(["neutral"] * len(df))
        ma10_arr = df["ma_10"].to_numpy() if "ma_10" in df.columns else np.array([np.nan] * len(df))
        ma240_arr = df["ma_240"].to_numpy() if "ma_240" in df.columns else np.array([np.nan] * len(df))

        out: Dict[pd.Timestamp, SignalSet] = {}
        n = len(df)
        i = 0
        while i < n:
            # Find run of same date (df is grouped by date when written)
            d = dates[i]
            j = i + 1
            while j < n and dates[j] == d:
                j += 1
            d_ts = pd.Timestamp(d)
            ma10_v = ma10_arr[i]
            ma240_v = ma240_arr[i]
            ss = SignalSet(
                date=d_ts,
                close=float(closes[i]),
                ma_10=None if (isinstance(ma10_v, float) and np.isnan(ma10_v)) else float(ma10_v),
                ma_240=None if (isinstance(ma240_v, float) and np.isnan(ma240_v)) else float(ma240_v),
            )
            ss.trend_type = str(trend_arr[i])
            ss.bearish_alignment = bool(bear_arr[i])
            ss.volume_zone = str(vz_arr[i])
            for k in range(i, j):
                if kinds[k] == "_NONE":
                    continue
                ss.signals.append(Signal(
                    kind=str(kinds[k]), source=str(sources[k]),
                    confidence=float(confs[k]),
                    detail=str(details[k]) if details[k] is not None else "",
                ))
            out[d_ts] = ss
            i = j
        self._mem[key] = out

    def get_signal_set(self, ticker: str, tf: str,
                        date: pd.Timestamp) -> Optional[SignalSet]:
        """O(1) lookup of cached SignalSet."""
        key = (ticker, tf)
        if key not in self._mem:
            self._load_into_mem(ticker, tf)
        return self._mem[key].get(pd.Timestamp(date))

    def get_bars(self, ticker: str, tf: str) -> pd.DataFrame:
        """Return cached bars (date-indexed) including ma_10/ma_240."""
        key = (ticker, tf)
        if key not in self._bars:
            self._load_into_mem(ticker, tf)
        return self._bars[key]

    def iter_dates(self, ticker: str, tf: str) -> List[pd.Timestamp]:
        bars = self.get_bars(ticker, tf)
        return list(bars.index)


# ---------------------------------------------------------------------------
# Convenience: build cache directly from DB
# ---------------------------------------------------------------------------
def build_cache_from_db(tickers: List[str],
                        timeframes: Iterable[str] = ("weekly",),
                        n_jobs: int = 1,
                        force: bool = False,
                        verbose: bool = True) -> Dict[str, int]:
    """Convenience: load daily prices from DuckDB and build cache."""
    from app.data.pit_db import cursor
    if verbose:
        print(f"[signal-cache] loading {len(tickers)} tickers from DB…")
    dfs: Dict[str, pd.DataFrame] = {}
    with cursor() as con:
        for tk in tickers:
            df = con.execute(
                "SELECT date, open, high, low, close, volume FROM prices "
                "WHERE ticker = ? ORDER BY date",
                [tk],
            ).df()
            if df.empty or len(df) < 250:
                continue
            df["date"] = pd.to_datetime(df["date"])
            dfs[tk] = df.reset_index(drop=True)
    if verbose:
        print(f"[signal-cache] {len(dfs)} tickers loaded")
    cache = SignalCache()
    return cache.build_for(list(dfs.keys()), dfs,
                            timeframes=timeframes,
                            force=force, n_jobs=n_jobs, verbose=verbose)
