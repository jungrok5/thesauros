"""Macro features for the ML panel.

Adds **per-date macro indicators** as features to the cross-sectional panel,
so the LightGBM model can learn regime-conditional patterns automatically:

  - vix              : CBOE VIX level
  - yield_curve      : 10Y-2Y spread (negative = inversion warning)
  - fed_funds_rate   : current Fed funds rate
  - m2_yoy_pct       : M2 growth YoY % (Friedman liquidity)
  - dxy              : US Dollar Index level
  - copper_yoy_pct   : Dr. Copper YoY (industrial demand)
  - regime_score     : aggregate regime score [-1, +1] from app.macro.state

All features use only data with date <= panel date (no look-ahead).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from app.data.pit_db import cursor


MACRO_FEATURE_SERIES = {
    "DFF": "fed_funds_rate",
    "T10Y2Y": "yield_curve_10y_2y",
    "T10YIE": "tips_breakeven_10y",
    "DFII10": "real_rate_10y",
    "WALCL": "fed_balance",
    "M2SL": "m2_supply",
    "CPIAUCSL": "cpi",
    "PCEPILFE": "core_pce",
    "PPIACO": "ppi",
    "UNRATE": "unemployment",
    "INDPRO": "industrial_production",
    "BAMLC0A0CM": "credit_spread_ig",
    "BAMLH0A0HYM2": "credit_spread_hy",
    "DX-Y.NYB": "dxy",
    "JPY=X": "usdjpy",
    "^VIX": "vix",
    "GC=F": "gold",
    "HG=F": "copper",
    "CL=F": "wti_oil",
    "^GSPC": "sp500",
    "^IXIC": "nasdaq",
}

# A pragmatic subset to actually feed the model. Adding all 21 risks
# multicollinearity and over-fit on a sparse panel.
ML_MACRO_FEATURES = [
    "macro_vix",
    "macro_yield_curve",
    "macro_real_rate",
    "macro_credit_spread",
    "macro_dxy_yoy",
    "macro_copper_yoy",
    "macro_m2_yoy",
    "macro_fed_funds",
]


def _load_series(series_id: str) -> pd.DataFrame:
    """Pull a macro series from DuckDB."""
    with cursor() as con:
        df = con.execute(
            "SELECT date, value FROM macro WHERE series_id = ? ORDER BY date",
            [series_id],
        ).df()
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    # Force ns precision so merge_asof against ns-typed pandas DatetimeIndex
    # succeeds (DuckDB returns datetime64[us]).
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def _yoy_pct(series: pd.Series) -> pd.Series:
    """YoY % change, calendar-day based."""
    s = series.sort_index()
    # rough: use 252-trading-day shift for daily, 12 for monthly
    shift_n = 252 if len(s) > 500 else 12
    return ((s / s.shift(shift_n)) - 1.0) * 100.0


def macro_features_panel(rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Return one row per rebalance date with macro features as-of that date.

    Uses backward as-of join (most recent value <= date), so no look-ahead.
    """
    dates = pd.DatetimeIndex(rebalance_dates).sort_values().unique()
    # Match the precision the macro loader produces.
    dates = pd.DatetimeIndex(dates).astype("datetime64[ns]")
    out = pd.DataFrame({"date": dates})

    # ---- load + as-of join each series ----
    def asof(series_id: str, col: str, transform: Optional[str] = None
             ) -> pd.Series:
        df = _load_series(series_id)
        if df.empty:
            return pd.Series(np.nan, index=range(len(dates)), name=col)
        df = df.sort_values("date")
        if transform == "yoy_pct":
            df["value"] = _yoy_pct(df.set_index("date")["value"]).values
        merged = pd.merge_asof(out[["date"]].sort_values("date"),
                               df, on="date", direction="backward")
        return merged["value"].rename(col).reset_index(drop=True)

    out["macro_vix"] = asof("^VIX", "macro_vix")
    out["macro_yield_curve"] = asof("T10Y2Y", "macro_yield_curve")
    out["macro_real_rate"] = asof("DFII10", "macro_real_rate")
    out["macro_credit_spread"] = asof("BAMLH0A0HYM2", "macro_credit_spread")
    out["macro_fed_funds"] = asof("DFF", "macro_fed_funds")
    out["macro_dxy_yoy"] = asof("DX-Y.NYB", "macro_dxy_yoy",
                                transform="yoy_pct")
    out["macro_copper_yoy"] = asof("HG=F", "macro_copper_yoy",
                                   transform="yoy_pct")
    out["macro_m2_yoy"] = asof("M2SL", "macro_m2_yoy", transform="yoy_pct")

    return out


def attach_macro(panel: pd.DataFrame) -> pd.DataFrame:
    """Add macro_* columns to a cross-sectional panel keyed by (date, ticker).

    Returns a new DataFrame; original is not mutated. Uses left-join — rows
    with no matching macro date are kept with NaN macro features.
    """
    if panel is None or panel.empty:
        return panel
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    macro = macro_features_panel(dates)
    return panel.merge(macro, on="date", how="left")
