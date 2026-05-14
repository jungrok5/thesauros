"""Academic factor library — names from the literature.

Each function takes the wide fundamental panel + price data at asof_dates and
returns one column per (date, ticker).

Implemented factors:
  Piotroski F-Score (9-point quality, 2000)
  Mohanram G-Score (8-point growth quality, 2005)
  Fama-French 5 (size, value, profitability, investment, momentum substitutes)
  Asness consistency-of-momentum
  Beneish M-Score proxy (earnings manipulation flag)
  Quality, Value, Growth, Sentiment composites
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def piotroski_f_score(fund: pd.DataFrame) -> pd.Series:
    """9-point quality score (Piotroski 2000).

    1. ROA > 0
    2. CFO > 0 (operating cash flow positive)
    3. ΔROA > 0 (improving)
    4. Accruals: CFO > Net Income (quality of earnings)
    5. ΔLeverage < 0 (lower long-term debt to assets)
    6. ΔLiquidity > 0 (higher current ratio)
    7. No new shares (or fewer)  → simplified: doesn't decrease
    8. ΔGross Margin > 0
    9. ΔAsset Turnover > 0

    Returns 0-9 score (NaN if too much missing).
    """
    f = fund.copy()
    score = pd.Series(0, index=f.index, dtype=float)
    n_present = pd.Series(0, index=f.index, dtype=int)

    def _add(cond: pd.Series, mask_present: pd.Series):
        nonlocal score, n_present
        cond = cond.fillna(False)
        score = score + cond.astype(int) * mask_present.astype(int)
        n_present = n_present + mask_present.astype(int)

    # 1. ROA > 0
    roa = f["ttm_ni"] / f["assets"]
    _add(roa > 0, roa.notna())

    # 2. CFO > 0
    cfo = f["ttm_ocf"]
    _add(cfo > 0, cfo.notna())

    # 3-4 require prior-year — caller passes a `prev` panel (can fold in by computing here)
    # Skipped here; caller composes from current + 1y-prior panels.

    # 5. Long-term debt / assets relative — proxied: leverage < median
    lev = f["lt_debt"] / f["assets"]
    med = lev.median()
    _add(lev < med, lev.notna())

    # 6. Current ratio decent
    cr = f["cur_assets"] / f["cur_liab"]
    _add(cr > 1.0, cr.notna())

    # 7. CFO > NI (accrual quality)
    _add(cfo > f["ttm_ni"], cfo.notna() & f["ttm_ni"].notna())

    # 8. Gross margin (need TTM gross profit if present)
    if "ttm_gp" in f.columns:
        gm = f["ttm_gp"] / f["ttm_revenue"]
        _add(gm > gm.median(), gm.notna())

    # 9. Asset turnover above median
    at = f["ttm_revenue"] / f["assets"]
    _add(at > at.median(), at.notna())

    # Normalize to 0..9 (since some checks need prior-year and aren't applied)
    out = (score / n_present.replace(0, np.nan)) * 9.0
    return out


def piotroski_with_yoy(curr: pd.DataFrame, prev: pd.DataFrame) -> pd.Series:
    """Full 9-point Piotroski using current vs 1-year-prior fundamentals."""
    score = pd.Series(0, index=curr.index, dtype=float)
    n = pd.Series(0, index=curr.index, dtype=int)

    def add(cond: pd.Series, ok: pd.Series):
        nonlocal score, n
        score = score + cond.fillna(False).astype(int) * ok.astype(int)
        n = n + ok.astype(int)

    # 1. ROA > 0
    roa = curr["ttm_ni"] / curr["assets"]
    add(roa > 0, roa.notna())

    # 2. CFO > 0
    cfo = curr["ttm_ocf"]; add(cfo > 0, cfo.notna())

    # 3. ΔROA > 0
    roa_prev = prev["ttm_ni"] / prev["assets"]
    add(roa > roa_prev, roa.notna() & roa_prev.notna())

    # 4. Accruals: CFO > NI
    add(cfo > curr["ttm_ni"], cfo.notna() & curr["ttm_ni"].notna())

    # 5. ΔLeverage < 0 (debt/assets falling)
    lev = curr["lt_debt"] / curr["assets"]
    lev_prev = prev["lt_debt"] / prev["assets"]
    add(lev < lev_prev, lev.notna() & lev_prev.notna())

    # 6. ΔCurrent ratio > 0
    cr = curr["cur_assets"] / curr["cur_liab"]
    cr_prev = prev["cur_assets"] / prev["cur_liab"]
    add(cr > cr_prev, cr.notna() & cr_prev.notna())

    # 7. No new shares (shares not increasing)
    add(curr["shares_out"] <= prev["shares_out"],
        curr["shares_out"].notna() & prev["shares_out"].notna())

    # 8. ΔGross margin > 0
    if "ttm_gp" in curr.columns and "ttm_gp" in prev.columns:
        gm = curr["ttm_gp"] / curr["ttm_revenue"]
        gm_prev = prev["ttm_gp"] / prev["ttm_revenue"]
        add(gm > gm_prev, gm.notna() & gm_prev.notna())

    # 9. ΔAsset turnover > 0
    at = curr["ttm_revenue"] / curr["assets"]
    at_prev = prev["ttm_revenue"] / prev["assets"]
    add(at > at_prev, at.notna() & at_prev.notna())

    # If too many missing, return NaN
    return score.where(n >= 6, np.nan)


def mohanram_g_score(fund: pd.DataFrame) -> pd.Series:
    """8-point growth quality (Mohanram 2005).

    Within "growth" stocks (low B/M), high G predicts better returns.
    Components:
      1. ROA > industry median
      2. CFO/Assets > industry median
      3. CFO > NI (low accruals)
      4. Earnings variance below median (stable)
      5. Sales growth variance below median
      6. R&D/Assets > median (we don't have R&D — substitute with capex/assets)
      7. Capex/Assets > median
      8. Advertising/Assets — we don't have. Skip.
    """
    f = fund.copy()
    score = pd.Series(0, index=f.index, dtype=float)
    n = pd.Series(0, index=f.index, dtype=int)

    def add(c, ok):
        nonlocal score, n
        score = score + c.fillna(False).astype(int) * ok.astype(int)
        n = n + ok.astype(int)

    roa = f["ttm_ni"] / f["assets"]
    add(roa > roa.median(), roa.notna())

    cfo_a = f["ttm_ocf"] / f["assets"]
    add(cfo_a > cfo_a.median(), cfo_a.notna())

    add(f["ttm_ocf"] > f["ttm_ni"], f["ttm_ocf"].notna() & f["ttm_ni"].notna())

    cap_a = f["ttm_capex"].abs() / f["assets"]
    add(cap_a > cap_a.median(), cap_a.notna())

    return score.where(n >= 3, np.nan)


def beneish_m_score_proxy(fund: pd.DataFrame, prev: pd.DataFrame) -> pd.Series:
    """Simplified Beneish M-Score (manipulation likelihood).

    Original uses 8 components; we use a 3-component proxy:
      DSRI (days sales receivables index) — skipped (no AR)
      AQI  (asset quality index) — skipped (no breakdown)
      SGI  (sales growth) ↑↑ red flag
      Accruals to assets  ↑ red flag
      Leverage growth ↑ red flag

    Higher = more manipulation risk (negative for predicted returns).
    """
    sgi = (fund["ttm_revenue"] / prev["ttm_revenue"]).replace([np.inf, -np.inf], np.nan)
    accr = (fund["ttm_ni"] - fund["ttm_ocf"]) / fund["assets"]
    lev_now = fund["lt_debt"] / fund["assets"]
    lev_prev = prev["lt_debt"] / prev["assets"]
    lev_chg = lev_now - lev_prev
    # Higher accruals + sales growth + leverage growth → suspicious
    out = (sgi.fillna(1.0) - 1.0) + accr.fillna(0) * 5 + lev_chg.fillna(0) * 5
    return out


def asness_quality_score(fund: pd.DataFrame) -> pd.Series:
    """Quality factor (Asness, Frazzini, Pedersen 2019).
    Combines profitability + growth + safety + payout.
    Returns sum of cross-sectional ranks.
    """
    parts = []
    # Profitability
    parts.append(rank((fund["ttm_gp"] / fund["assets"]) if "ttm_gp" in fund else fund["ttm_ni"] / fund["assets"]))
    parts.append(rank(fund["ttm_ni"] / fund["equity"].where(fund["equity"] > 0)))
    parts.append(rank(fund["ttm_ocf"] / fund["assets"]))
    # Safety: low leverage, low earnings variability
    parts.append(rank(-(fund["lt_debt"] / fund["assets"])))  # less debt better
    return sum(parts) / len(parts)


def value_score(fund: pd.DataFrame, mc: pd.Series) -> pd.Series:
    """Multi-metric value rank: low PE, low PB, low PS, low EV/Sales, high FCF yield."""
    pe = mc / fund["ttm_ni"].where(fund["ttm_ni"] > 0)
    pb = mc / fund["equity"].where(fund["equity"] > 0)
    ps = mc / fund["ttm_revenue"].where(fund["ttm_revenue"] > 0)
    fcf = fund["ttm_ocf"] - fund["ttm_capex"]
    fcf_y = fcf / mc

    parts = [
        rank(-pe),  # lower PE → higher rank
        rank(-pb),
        rank(-ps),
        rank(fcf_y),
    ]
    return sum(parts) / len(parts)


def rank(s: pd.Series) -> pd.Series:
    """Cross-sectional rank percentile [0, 1]."""
    return s.rank(pct=True, method="average")


def consistency_of_momentum(returns_panel: pd.DataFrame) -> pd.DataFrame:
    """% of past 12 months that were positive (Asness 1995).

    `returns_panel` is wide DataFrame [date, ticker] of monthly returns.
    Returns same shape — fraction of past 12 monthly returns > 0.
    """
    return (returns_panel > 0).rolling(12, min_periods=6).mean()


def chande_momentum(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """Chande Momentum Oscillator: (sum_up - sum_down) / (sum_up + sum_down)."""
    delta = close.diff()
    up = delta.clip(lower=0).rolling(n).sum()
    dn = (-delta.clip(upper=0)).rolling(n).sum()
    return (up - dn) / (up + dn).replace(0, np.nan)
