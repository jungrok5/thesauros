"""Build the full feature panel for ML training (vectorized).

Steps:
  1. Pick rebalance dates (every Nth trading day).
  2. Compute technical features on the wide price matrix (vectorized).
  3. Compute fundamental features per (date, ticker) using vectorized PIT lookup.
  4. Compute valuation ratios using current price + fundamentals.
  5. Add cross-sectional ranks.
  6. Compute forward 21-day return as the target.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

import numpy as np
import pandas as pd

from app.config import FORWARD_HORIZON
from app.data.pit_db import cursor
from app.features.fund_vec import build_fundamental_panel
from app.features.technical import technical_panel


FUND_FEATURES = [
    "roa_ttm", "roe_ttm",
    "op_margin", "gross_margin", "net_margin",
    "debt_to_equity", "liab_to_assets", "current_ratio", "cash_ratio",
    "asset_turnover",
    "revenue_growth_yoy", "earnings_growth_yoy",
    "ev_to_revenue", "ev_to_ebitda_proxy",
    "pe", "pb", "ps", "fcf_yield",
    "log_market_cap",
]

TECH_FEATURES = [
    "mom_1m", "mom_3m", "mom_6m", "mom_12_1", "mom_12m",
    "vol_20", "vol_60", "dd_252",
    "px_to_sma50", "px_to_sma200", "sma50_to_sma200",
    "rsi_14", "macd_hist", "rev_5d",
]

ALL_FEATURES = FUND_FEATURES + TECH_FEATURES


def load_prices_wide(start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    where = []
    args: list = []
    if start: where.append("date >= ?"); args.append(start)
    if end: where.append("date <= ?"); args.append(end)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with cursor() as con:
        df = con.execute(
            f"SELECT date, ticker, adj_close FROM prices {w} ORDER BY date, ticker",
            args,
        ).df()
    if df.empty:
        return df
    wide = df.pivot(index="date", columns="ticker", values="adj_close")
    wide.index = pd.to_datetime(wide.index)
    return wide


def rebalance_dates(prices: pd.DataFrame, every_n_days: int = 21,
                    start: Optional[str] = None) -> List[pd.Timestamp]:
    if prices.empty:
        return []
    dates = list(prices.index)
    if start:
        s = pd.to_datetime(start)
        dates = [d for d in dates if d >= s]
    return [dates[i] for i in range(0, len(dates), every_n_days)]


def _cross_sectional_rank(panel: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    panel = panel.copy()
    for c in cols:
        if c in panel.columns:
            panel[c + "_rk"] = panel.groupby("date")[c].rank(pct=True, method="average")
    return panel


def build_panel(start: str = "2014-01-01",
                end: Optional[str] = None,
                rebalance_n: int = 21,
                with_target: bool = True,
                verbose: bool = True) -> pd.DataFrame:
    fetch_start = str((pd.to_datetime(start) - pd.Timedelta(days=400)).date())
    prices = load_prices_wide(start=fetch_start, end=end)
    if prices.empty:
        raise RuntimeError("No prices in DB. Run ingestion first.")

    if verbose:
        print(f"[panel] prices: {prices.shape}, range {prices.index.min().date()} → {prices.index.max().date()}")

    # Tech features (vectorized over the wide matrix)
    tech = technical_panel(prices)
    tech["date"] = pd.to_datetime(tech["date"])
    if verbose:
        print(f"[panel] tech features: {tech.shape}")

    rdates = rebalance_dates(prices, every_n_days=rebalance_n, start=start)
    if verbose:
        print(f"[panel] rebalance dates: {len(rdates)} from {rdates[0].date()} to {rdates[-1].date()}")

    # Fundamental panel — vectorized PIT
    if verbose:
        print(f"[panel] computing fundamentals (vectorized)...")
    asof_idx = pd.DatetimeIndex(rdates)
    fund = build_fundamental_panel(asof_idx)
    if verbose:
        print(f"[panel] fundamental rows: {len(fund)}")

    # Slice tech to rebalance dates
    tech_rb = tech[tech["date"].isin(asof_idx)].copy()

    # Merge tech + fund on (date, ticker)
    panel = tech_rb.merge(fund, on=["date", "ticker"], how="left")

    # Add close price at rebalance date
    px_long = prices.loc[asof_idx].stack().rename("close").reset_index()
    px_long.columns = ["date", "ticker", "close"]
    panel = panel.merge(px_long, on=["date", "ticker"], how="left")

    # Valuation ratios (price × stock)
    shares = panel.get("__shares_out")
    equity = panel.get("__equity")
    rev = panel.get("__ttm_revenue")
    ni = panel.get("__ttm_ni")
    debt = panel.get("__total_debt")
    cash = panel.get("__cash")
    fcf = panel.get("fcf_ttm")
    mc = (panel["close"] * shares) if shares is not None else None
    panel["log_market_cap"] = np.log(mc).where(mc > 0) if mc is not None else np.nan
    if mc is not None:
        ev = mc + (debt.fillna(0) if debt is not None else 0) - (cash.fillna(0) if cash is not None else 0)
        panel["pe"] = (mc / ni).where(ni > 0)
        panel["pb"] = (mc / equity).where(equity > 0)
        panel["ps"] = (mc / rev).where(rev > 0)
        panel["ev_to_revenue"] = (ev / rev).where(rev > 0)
        panel["ev_to_ebitda_proxy"] = (ev / (ni + fcf.fillna(0))).where(
            (ni + fcf.fillna(0)) > 0,
        )
        panel["fcf_yield"] = (fcf / mc).where(mc > 0)
    else:
        for c in ["pe", "pb", "ps", "ev_to_revenue", "ev_to_ebitda_proxy", "fcf_yield"]:
            panel[c] = np.nan

    # Drop helper raw columns
    panel = panel.drop(columns=[c for c in panel.columns if c.startswith("__")
                                or c in ("ttm_revenue_yago", "ttm_ni_yago",
                                         "lt_debt", "lt_debt_nc", "shares_out")
                                ], errors="ignore")

    # Add cross-sectional ranks
    panel = _cross_sectional_rank(panel, ALL_FEATURES)

    # Forward target
    if with_target:
        wide = prices.copy()
        fwd = (wide.shift(-FORWARD_HORIZON) / wide) - 1.0
        fwd_long = fwd.stack().rename("y_fwd").reset_index()
        fwd_long["date"] = pd.to_datetime(fwd_long["date"])
        panel = panel.merge(fwd_long, on=["date", "ticker"], how="left")

    return panel
