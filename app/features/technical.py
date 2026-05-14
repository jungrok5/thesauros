"""Price-only technical features. All indicators use rolling windows up to the
panel's date — no future leak by construction (we always slice closed up to t).
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_hist(close: pd.Series) -> pd.Series:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def technical_panel(prices: pd.DataFrame) -> pd.DataFrame:
    """`prices` is wide DataFrame [date x ticker] of adjusted close.
    Returns a long DataFrame with one row per (date, ticker) and many columns.
    """
    if prices.empty:
        return pd.DataFrame()

    close = prices.sort_index()
    rets = close.pct_change()

    feats = {}

    # Momentum
    feats["mom_1m"] = close.pct_change(21)
    feats["mom_3m"] = close.pct_change(63)
    feats["mom_6m"] = close.pct_change(126)
    feats["mom_12_1"] = (close.shift(21) / close.shift(252)) - 1
    feats["mom_12m"] = close.pct_change(252)

    # Volatility / risk
    feats["vol_20"] = rets.rolling(20).std() * np.sqrt(252)
    feats["vol_60"] = rets.rolling(60).std() * np.sqrt(252)
    feats["dd_252"] = (close / close.rolling(252, min_periods=60).max()) - 1.0

    # Trend
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feats["px_to_sma50"] = (close / sma50) - 1
    feats["px_to_sma200"] = (close / sma200) - 1
    feats["sma50_to_sma200"] = (sma50 / sma200) - 1

    # Mean revert / oscillators
    feats["rsi_14"] = close.apply(lambda s: _rsi(s, 14))
    feats["macd_hist"] = close.apply(_macd_hist)

    # 5-day reversal (short-term mean revert anomaly)
    feats["rev_5d"] = close.pct_change(5)

    # Stack to long form: rows = (date, ticker), cols = features
    pieces = []
    for name, df in feats.items():
        s = df.stack().rename(name)
        pieces.append(s)
    panel = pd.concat(pieces, axis=1).reset_index()
    panel.columns = ["date", "ticker"] + list(feats.keys())
    return panel
