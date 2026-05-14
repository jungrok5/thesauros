"""Phase 2 pipeline — adds:
  - Piotroski F-Score, Mohanram G-Score, Beneish M-Score proxy
  - Asness quality / consistency-of-momentum
  - Sector neutralization (within-sector z-score)
  - Cross-sectional rank target (deciles)
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from app.config import FORWARD_HORIZON
from app.data.pit_db import cursor
from app.features.fund_vec import build_fundamental_panel
from app.features.factor_zoo import (
    asness_quality_score, beneish_m_score_proxy, chande_momentum,
    mohanram_g_score, piotroski_with_yoy, value_score,
)
from app.features.technical import technical_panel


# Phase 2 features (combined fund + tech + new factor zoo)
FUND_FEATURES_V3 = [
    "roa_ttm", "roe_ttm",
    "op_margin", "gross_margin", "net_margin",
    "debt_to_equity", "liab_to_assets", "current_ratio", "cash_ratio",
    "asset_turnover",
    "revenue_growth_yoy", "earnings_growth_yoy",
    "ev_to_revenue", "fcf_yield", "log_market_cap",
    "pe", "pb", "ps",
    # New factor zoo:
    "piotroski_f", "mohanram_g", "beneish_m",
    "asness_quality", "value_composite",
    "earnings_yield",   # 1/PE clamped
    "fcf_to_assets", "ocf_to_assets",
    "sales_to_assets", "rnd_proxy",   # capex/assets stand-in
    "dividend_to_fcf", "leverage", "tangibility",
]

TECH_FEATURES_V3 = [
    "mom_1m", "mom_3m", "mom_6m", "mom_12_1", "mom_12m",
    "vol_20", "vol_60", "dd_252",
    "px_to_sma50", "px_to_sma200", "sma50_to_sma200",
    "rsi_14", "macd_hist", "rev_5d",
    "chande_14",
    "consistency_12m",
]

ALL_V3 = FUND_FEATURES_V3 + TECH_FEATURES_V3


def load_prices_wide(start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    where = []; args: list = []
    if start: where.append("date >= ?"); args.append(start)
    if end: where.append("date <= ?"); args.append(end)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with cursor() as con:
        df = con.execute(
            f"SELECT date, ticker, adj_close FROM prices {w} ORDER BY date, ticker",
            args,
        ).df()
    if df.empty: return df
    wide = df.pivot(index="date", columns="ticker", values="adj_close")
    wide.index = pd.to_datetime(wide.index)
    return wide


def load_universe_with_sector() -> pd.DataFrame:
    with cursor() as con:
        return con.execute(
            "SELECT ticker, name, sector FROM universe"
        ).df()


def rebalance_dates(prices: pd.DataFrame, every_n_days: int = 21,
                    start: Optional[str] = None) -> List[pd.Timestamp]:
    if prices.empty: return []
    dates = list(prices.index)
    if start:
        s = pd.to_datetime(start)
        dates = [d for d in dates if d >= s]
    return [dates[i] for i in range(0, len(dates), every_n_days)]


def _sector_neutralize(panel: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """For each (date, sector), z-score each feature, replacing the original.
    Adds `*_sn` (sector-neutral) columns alongside original.
    """
    panel = panel.copy()
    if "sector" not in panel.columns:
        return panel

    for c in cols:
        if c not in panel.columns:
            continue
        s = panel.groupby(["date", "sector"])[c].transform(
            lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-12) if x.notna().sum() >= 3 else x
        )
        panel[c + "_sn"] = s.clip(-3, 3)
    return panel


def _add_factor_zoo(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute Piotroski / Mohanram / Beneish / Asness / value composite per (date)."""
    panel = panel.copy()
    out_pio = []; out_moh = []; out_ben = []; out_asn = []; out_val = []

    for d, g in panel.groupby("date", sort=False):
        # Build frames with the column names that piotroski_with_yoy expects
        cols_now = {
            "ttm_ni": g["__ttm_ni"], "ttm_revenue": g["__ttm_revenue"],
            "ttm_ocf": g.get("ttm_ocf"), "ttm_capex": g.get("ttm_capex"),
            "ttm_gp": g.get("ttm_gp"),
            "assets": g.get("assets"), "cur_assets": g.get("cur_assets"),
            "cur_liab": g.get("cur_liab"), "equity": g.get("__equity"),
            "lt_debt": g.get("__total_debt"), "shares_out": g.get("__shares_out"),
        }
        curr = pd.DataFrame({k: v for k, v in cols_now.items() if v is not None}, index=g.index)
        # Year-ago panel (same shape, _prev columns)
        prev = pd.DataFrame({
            "ttm_ni": g.get("ttm_ni_yago"),
            "ttm_revenue": g.get("ttm_revenue_yago"),
            "ttm_ocf": g.get("ttm_ocf_prev"),
            "ttm_gp": g.get("ttm_gp_prev"),
            "assets": g.get("assets_prev"),
            "cur_assets": g.get("cur_assets_prev"),
            "cur_liab": g.get("cur_liab_prev"),
            "equity": g.get("equity_prev"),
            "lt_debt": g.get("lt_debt_prev"),
            "shares_out": g.get("shares_out_prev"),
        }, index=g.index)

        try:
            pio = piotroski_with_yoy(curr, prev)
        except Exception:
            pio = pd.Series(np.nan, index=g.index)
        try:
            moh = mohanram_g_score(curr)
        except Exception:
            moh = pd.Series(np.nan, index=g.index)
        try:
            ben = beneish_m_score_proxy(curr, prev)
        except Exception:
            ben = pd.Series(np.nan, index=g.index)
        try:
            asn = asness_quality_score(curr)
        except Exception:
            asn = pd.Series(np.nan, index=g.index)
        try:
            mc = g["close"] * g["__shares_out"]
            val = value_score(curr, mc)
        except Exception:
            val = pd.Series(np.nan, index=g.index)

        out_pio.append(pio); out_moh.append(moh); out_ben.append(ben)
        out_asn.append(asn); out_val.append(val)

    panel["piotroski_f"] = pd.concat(out_pio).sort_index()
    panel["mohanram_g"] = pd.concat(out_moh).sort_index()
    panel["beneish_m"] = pd.concat(out_ben).sort_index()
    panel["asness_quality"] = pd.concat(out_asn).sort_index()
    panel["value_composite"] = pd.concat(out_val).sort_index()
    return panel


def build_panel_v3(start: str = "2014-01-01",
                   end: Optional[str] = None,
                   rebalance_n: int = 21,
                   with_target: bool = True,
                   sector_neutralize: bool = True,
                   verbose: bool = True) -> pd.DataFrame:
    fetch_start = str((pd.to_datetime(start) - pd.Timedelta(days=400)).date())
    prices = load_prices_wide(start=fetch_start, end=end)
    if prices.empty: raise RuntimeError("No prices in DB.")
    if verbose:
        print(f"[v3] prices {prices.shape} {prices.index.min().date()} → {prices.index.max().date()}")

    # Tech features
    tech = technical_panel(prices)
    tech["date"] = pd.to_datetime(tech["date"])

    # Add Chande momentum + consistency
    chande = chande_momentum(prices, 14).stack().rename("chande_14").reset_index()
    chande["date"] = pd.to_datetime(chande["date"])
    tech = tech.merge(chande, on=["date", "ticker"], how="left")

    # Consistency of momentum (12m fraction positive)
    monthly = prices.resample("M").last()
    m_ret = monthly.pct_change()
    consist = (m_ret > 0).rolling(12, min_periods=6).mean()
    consist_long = consist.stack().rename("consistency_12m").reset_index()
    consist_long["date"] = pd.to_datetime(consist_long["date"])
    # As-of merge: use the most recent month-end consistency for each daily date
    consist_long = consist_long.sort_values("date")
    tech_sorted = tech.sort_values("date")
    tech = pd.merge_asof(tech_sorted, consist_long, by="ticker", on="date",
                         direction="backward")

    if verbose:
        print(f"[v3] tech features {tech.shape}")

    # Rebalance dates
    rdates = rebalance_dates(prices, every_n_days=rebalance_n, start=start)
    asof_idx = pd.DatetimeIndex(rdates)
    if verbose:
        print(f"[v3] rebalance dates {len(rdates)} ({rdates[0].date()} → {rdates[-1].date()})")

    # Fundamentals with year-ago snapshot
    if verbose:
        print("[v3] computing fundamentals (with yago snapshots)...")
    fund = build_fundamental_panel(asof_idx, include_yago=True)
    if verbose:
        print(f"[v3] fundamentals {fund.shape}")

    # Slice tech to rebalance dates
    tech_rb = tech[tech["date"].isin(asof_idx)].copy()

    # Merge
    panel = tech_rb.merge(fund, on=["date", "ticker"], how="left")

    # Add close at rebalance date
    px_long = prices.loc[asof_idx].stack().rename("close").reset_index()
    px_long.columns = ["date", "ticker", "close"]
    panel = panel.merge(px_long, on=["date", "ticker"], how="left")

    # Add sector
    uni = load_universe_with_sector()
    panel = panel.merge(uni, on="ticker", how="left")

    # Valuation features
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
        panel["fcf_yield"] = (fcf / mc).where(mc > 0)
        panel["earnings_yield"] = (ni / mc).where(mc > 0)

    # Additional ratios
    panel["fcf_to_assets"] = panel.get("fcf_ttm") / panel.get("assets")
    panel["ocf_to_assets"] = panel.get("ttm_ocf") / panel.get("assets")
    panel["sales_to_assets"] = panel.get("ttm_revenue") / panel.get("assets")
    panel["rnd_proxy"] = panel.get("ttm_capex").abs() / panel.get("assets")
    panel["dividend_to_fcf"] = np.nan  # placeholder (no dividend data yet)
    panel["leverage"] = panel.get("__total_debt") / (panel.get("__total_debt") + panel.get("__equity"))
    panel["tangibility"] = (panel.get("assets") - panel.get("cur_assets")) / panel.get("assets")

    # Factor zoo
    if verbose: print("[v3] computing factor zoo (Piotroski/Mohanram/Beneish/Asness/Value)...")
    panel = _add_factor_zoo(panel)

    # Sector neutralization (replaces raw with sector-neutral z-score)
    if sector_neutralize:
        if verbose: print("[v3] sector-neutralizing features...")
        panel = _sector_neutralize(panel, ALL_V3)

    # Cross-sectional rank features (kept alongside)
    for c in ALL_V3:
        if c in panel.columns:
            panel[c + "_rk"] = panel.groupby("date")[c].rank(pct=True, method="average")

    # Drop helper raw columns
    drop_cols = [c for c in panel.columns if c.startswith("__")
                 or c.endswith("_yago") or c.endswith("_prev")
                 or c in ("ttm_revenue", "ttm_ni", "ttm_op", "ttm_gp",
                          "ttm_ocf", "ttm_capex",
                          "assets", "cur_assets", "cur_liab", "equity",
                          "lt_debt", "lt_debt_nc", "cash", "shares_out",
                          "liabilities", "fcf_ttm", "accruals")]
    panel = panel.drop(columns=drop_cols, errors="ignore")

    # Forward target — both raw and decile rank
    if with_target:
        wide = prices.copy()
        fwd = (wide.shift(-FORWARD_HORIZON) / wide) - 1.0
        fwd_long = fwd.stack().rename("y_fwd").reset_index()
        fwd_long["date"] = pd.to_datetime(fwd_long["date"])
        panel = panel.merge(fwd_long, on=["date", "ticker"], how="left")
        # Cross-sectional rank target (decile, 0..9)
        panel["y_rank"] = panel.groupby("date")["y_fwd"].rank(pct=True, method="average")

    return panel
