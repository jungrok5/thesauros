"""Book V4 signal features for ML — Phase 1A signal fusion.

Pulls weekly cached signals (signal_cache) and converts them into
per-(date, ticker) features the ML model can learn from.

Look-ahead safety:
    For each (date D, ticker), we use the most recent weekly bar with
    date <= D. Built on `pd.merge_asof(direction="backward")` to
    enforce no future info leakage.

Caching: relies on `app.cache.signal_cache.SignalCache` which is auto
hash-invalidated when book signal code changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


BOOK_FEATURES: List[str] = [
    "book_enter_max_conf",      # 가장 가까운 weekly bar 의 ENTER 최대 confidence
    "book_pyramid_max_conf",
    "book_warn_max_conf",
    "book_exit_max_conf",
    "book_signal_count_4w",     # 최근 4주 신호 발동 수 (any kind)
    "book_enter_count_12w",
    "book_exit_count_12w",
    "book_trend_uptrend",       # one-hot: trend_type == "uptrend"
    "book_trend_sideways",      # 책: 박스권 매매 금지
    "book_trend_downtrend",
    "book_bearish_alignment",   # 책: 역배열 매수 금지
    "book_vol_zone_support",    # 마덧값 지지
    "book_vol_zone_resistance",
    "book_ma10_above",          # close > ma_10 (책의 진정한 추세선)
    "book_ma240_above",         # close > ma_240 (책의 죽은 차트 라인)
]


def _ticker_signal_summary(ticker: str,
                            cache_dir: Path) -> Optional[pd.DataFrame]:
    """Read the ticker's weekly signal parquet and reduce to per-week summary.

    Returns DataFrame with columns:
        date, close, ma_10, ma_240, trend_type, bearish_alignment, volume_zone,
        enter_max_conf, pyramid_max_conf, warn_max_conf, exit_max_conf
    """
    sig_path = cache_dir / "weekly" / f"{ticker.replace('/', '_').replace(':', '_')}.parquet"
    bars_path = cache_dir / "weekly" / f"{ticker.replace('/', '_').replace(':', '_')}__bars.parquet"
    if not sig_path.exists() or not bars_path.exists():
        return None
    sig = pd.read_parquet(sig_path)
    bars = pd.read_parquet(bars_path)
    sig["date"] = pd.to_datetime(sig["date"])
    bars["date"] = pd.to_datetime(bars["date"])

    # 1) per-bar context from first row of each date in sig (trend / alignment / zone)
    # Sig is sorted by (date, then kind rows). One date may have many rows.
    sig_context = (
        sig.drop_duplicates("date", keep="first")[
            ["date", "trend_type", "bearish_alignment", "volume_zone"]
        ].copy()
    )

    # 2) per-date max confidence by kind
    pivot = (
        sig[sig["kind"].isin(["ENTER", "PYRAMID", "WARN", "EXIT"])]
        .groupby(["date", "kind"])["confidence"].max()
        .unstack(fill_value=0.0)
        .reset_index()
    )
    for k in ("ENTER", "PYRAMID", "WARN", "EXIT"):
        if k not in pivot.columns:
            pivot[k] = 0.0
    pivot = pivot.rename(columns={
        "ENTER": "enter_max_conf",
        "PYRAMID": "pyramid_max_conf",
        "WARN": "warn_max_conf",
        "EXIT": "exit_max_conf",
    })

    # 3) bars provide close, ma_10, ma_240
    out = bars[["date", "close", "ma_10", "ma_240"]].merge(
        sig_context, on="date", how="left"
    ).merge(pivot, on="date", how="left")

    # Fill defaults for weeks with no signals at all
    out["trend_type"] = out["trend_type"].fillna("unknown")
    out["bearish_alignment"] = out["bearish_alignment"].fillna(False)
    out["volume_zone"] = out["volume_zone"].fillna("neutral")
    for c in ("enter_max_conf", "pyramid_max_conf",
              "warn_max_conf", "exit_max_conf"):
        out[c] = out[c].fillna(0.0)

    out = out.sort_values("date").reset_index(drop=True)

    # 4) rolling counts of signals in past 4w / 12w (windows of weekly bars)
    out["__any_signal"] = (
        (out["enter_max_conf"] > 0)
        | (out["pyramid_max_conf"] > 0)
        | (out["warn_max_conf"] > 0)
        | (out["exit_max_conf"] > 0)
    ).astype(int)
    out["__enter_flag"] = (out["enter_max_conf"] > 0).astype(int)
    out["__exit_flag"] = (out["exit_max_conf"] > 0).astype(int)
    out["signal_count_4w"] = (
        out["__any_signal"].rolling(window=4, min_periods=1).sum()
    )
    out["enter_count_12w"] = (
        out["__enter_flag"].rolling(window=12, min_periods=1).sum()
    )
    out["exit_count_12w"] = (
        out["__exit_flag"].rolling(window=12, min_periods=1).sum()
    )

    out = out.drop(columns=["__any_signal", "__enter_flag", "__exit_flag"])
    out["ticker"] = ticker
    return out


def attach_book_signals(panel: pd.DataFrame,
                        cache_dir: Optional[Path] = None,
                        verbose: bool = False) -> pd.DataFrame:
    """Left-join book V4 signal features onto a (date, ticker) panel.

    PIT-safe: for each (date D, ticker), uses most recent weekly bar with
    date <= D via `pd.merge_asof(direction="backward")`.

    Tickers/dates with no signals → all features 0 / "neutral".
    """
    if panel is None or panel.empty:
        return panel

    from app.cache.signal_cache import DEFAULT_CACHE_DIR
    cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
    if not cache_dir.exists():
        if verbose:
            print(f"[book-features] no cache at {cache_dir}, filling defaults")
        out = panel.copy()
        for col in BOOK_FEATURES:
            out[col] = 0.0
        return out

    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])

    # Load all summaries per ticker (only tickers present in panel)
    tickers = panel["ticker"].unique().tolist()
    summaries = []
    n_loaded = 0
    for tk in tickers:
        s = _ticker_signal_summary(tk, cache_dir)
        if s is not None and not s.empty:
            summaries.append(s)
            n_loaded += 1
    if verbose:
        print(f"[book-features] loaded summaries for {n_loaded}/{len(tickers)} tickers")

    if not summaries:
        for col in BOOK_FEATURES:
            panel[col] = 0.0
        return panel

    all_sig = pd.concat(summaries, ignore_index=True)
    # Force ns precision on both sides (parquet returns us by default)
    all_sig["date"] = pd.to_datetime(all_sig["date"]).astype("datetime64[ns]")
    panel["date"] = panel["date"].astype("datetime64[ns]")

    # merge_asof requires both sides sorted by `on` key (date) globally
    all_sig = all_sig.sort_values("date").reset_index(drop=True)
    panel_idx_orig = panel.index.copy()
    panel = panel.sort_values("date").reset_index(drop=True)

    merged = pd.merge_asof(
        panel, all_sig,
        by="ticker", on="date", direction="backward",
        suffixes=("", "__book"),
    )

    # Derive one-hot trend_type
    trend = merged["trend_type"].fillna("unknown").astype(str)
    merged["book_trend_uptrend"] = (trend == "uptrend").astype(int)
    merged["book_trend_sideways"] = (trend == "sideways").astype(int)
    merged["book_trend_downtrend"] = (trend == "downtrend").astype(int)
    merged["book_bearish_alignment"] = merged["bearish_alignment"].fillna(
        False
    ).astype(int)

    vz = merged["volume_zone"].fillna("neutral").astype(str)
    merged["book_vol_zone_support"] = (vz == "support").astype(int)
    merged["book_vol_zone_resistance"] = (vz == "resistance").astype(int)

    # ma_10 / ma_240 comparisons (use book's close from same weekly bar)
    bk_close = merged["close__book"] if "close__book" in merged.columns else merged.get("close")
    merged["book_ma10_above"] = (
        (bk_close > merged["ma_10"]).fillna(False).astype(int)
    )
    merged["book_ma240_above"] = (
        (bk_close > merged["ma_240"]).fillna(False).astype(int)
    )

    # Confidence + count features
    merged["book_enter_max_conf"] = merged["enter_max_conf"].fillna(0.0)
    merged["book_pyramid_max_conf"] = merged["pyramid_max_conf"].fillna(0.0)
    merged["book_warn_max_conf"] = merged["warn_max_conf"].fillna(0.0)
    merged["book_exit_max_conf"] = merged["exit_max_conf"].fillna(0.0)
    merged["book_signal_count_4w"] = merged["signal_count_4w"].fillna(0.0)
    merged["book_enter_count_12w"] = merged["enter_count_12w"].fillna(0.0)
    merged["book_exit_count_12w"] = merged["exit_count_12w"].fillna(0.0)

    # Drop intermediate columns (also strip any leaked pivot columns like _NONE)
    drop_cols = [c for c in (
        "ma_10", "ma_240", "trend_type", "bearish_alignment", "volume_zone",
        "enter_max_conf", "pyramid_max_conf", "warn_max_conf", "exit_max_conf",
        "signal_count_4w", "enter_count_12w", "exit_count_12w",
        "close__book", "_NONE",
    ) if c in merged.columns]
    # Also drop book's `close` column if panel did not originally have one
    # (it leaked in via the merge). If panel had `close`, it kept its name.
    merged = merged.drop(columns=drop_cols, errors="ignore")

    # Ensure all BOOK_FEATURES present
    for col in BOOK_FEATURES:
        if col not in merged.columns:
            merged[col] = 0.0

    return merged
