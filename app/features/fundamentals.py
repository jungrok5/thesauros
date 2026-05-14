"""PIT-correct fundamental feature builder.

For an "as-of date" t and a ticker:
  1. SELECT all rows from `fundamentals` where filed_date <= t.
  2. For each concept, take the row with the LATEST period_end among those.
     If multiple were filed for the same period_end (amendments), take the
     one with the latest filed_date <= t.
  3. Compute derived features (TTM, growth, ratios) only from rows already
     visible at t.

This guarantees zero look-ahead leak: future filings are simply not in the
candidate set.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from app.data.pit_db import cursor


# Concept fallbacks — SEC issuers report revenue under different us-gaap tags.
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]


def _latest_visible_facts(ticker: str, asof: pd.Timestamp,
                          concepts: Iterable[str]) -> Dict[str, dict]:
    """For each concept, return the latest visible (period_end, value, fp, fy, filed_date).

    Selection rule:
      - filtered to filed_date <= asof
      - prefer rows with fp != FY only when looking at quarterly aggregates
        (the caller decides; default here returns whatever has the latest period_end).
    """
    placeholders = ",".join("?" * len(concepts))
    q = f"""
        SELECT concept, period_end, fp, fy, filed_date, value
        FROM fundamentals
        WHERE ticker = ? AND concept IN ({placeholders}) AND filed_date <= ?
    """
    with cursor() as con:
        df = con.execute(q, [ticker, *concepts, asof.date()]).df()
    if df.empty:
        return {}
    out: Dict[str, dict] = {}
    for c, sub in df.groupby("concept"):
        sub = sub.sort_values(["period_end", "filed_date"], ascending=[False, False])
        row = sub.iloc[0]
        out[c] = {
            "period_end": pd.Timestamp(row["period_end"]),
            "fp": row["fp"], "fy": row["fy"],
            "filed_date": pd.Timestamp(row["filed_date"]),
            "value": float(row["value"]),
        }
    return out


def _ttm(ticker: str, asof: pd.Timestamp, concept: str,
         min_q: int = 4) -> Optional[float]:
    """Trailing-twelve-month sum of a flow concept (revenue, net income, OCF…).

    Picks the 4 most-recent quarterly observations whose filed_date <= asof
    AND whose fp ∈ (Q1,Q2,Q3,Q4). Falls back to FY value if quarters missing.
    """
    with cursor() as con:
        df = con.execute(
            """SELECT period_end, fp, fy, filed_date, value
               FROM fundamentals
               WHERE ticker=? AND concept=? AND filed_date<=?
               ORDER BY period_end DESC, filed_date DESC""",
            [ticker, concept, asof.date()],
        ).df()
    if df.empty:
        return None
    # Deduplicate: keep latest filed_date per period_end
    df = df.drop_duplicates(subset=["period_end"], keep="first")
    # Try quarterly (Q1..Q4) first
    qrtly = df[df["fp"].isin(["Q1", "Q2", "Q3", "Q4"])].head(min_q)
    if len(qrtly) >= min_q:
        return float(qrtly["value"].sum())
    # FY fallback: most recent FY value (already represents TTM at fiscal year end)
    fy = df[df["fp"] == "FY"].head(1)
    if len(fy):
        return float(fy["value"].iloc[0])
    return None


def _ttm_revenue(ticker: str, asof: pd.Timestamp) -> Optional[float]:
    for c in REVENUE_CONCEPTS:
        v = _ttm(ticker, asof, c)
        if v is not None:
            return v
    return None


def fundamental_features(ticker: str, asof: pd.Timestamp) -> Dict[str, Optional[float]]:
    """Return a dict of fundamental ratios visible at `asof`."""
    f: Dict[str, Optional[float]] = {}

    # Stocks of balance-sheet items (latest snapshot)
    bs_concepts = [
        "Assets", "AssetsCurrent",
        "Liabilities", "LiabilitiesCurrent",
        "StockholdersEquity",
        "LongTermDebt", "LongTermDebtNoncurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "CommonStockSharesOutstanding",
    ]
    bs = _latest_visible_facts(ticker, asof, bs_concepts)

    # TTM flows
    ttm_revenue = _ttm_revenue(ticker, asof)
    ttm_net_income = _ttm(ticker, asof, "NetIncomeLoss")
    ttm_op_income = _ttm(ticker, asof, "OperatingIncomeLoss")
    ttm_ocf = _ttm(ticker, asof, "NetCashProvidedByUsedInOperatingActivities")
    ttm_capex = _ttm(ticker, asof, "PaymentsToAcquirePropertyPlantAndEquipment")
    ttm_gp = _ttm(ticker, asof, "GrossProfit")
    ttm_dep = (_ttm(ticker, asof, "DepreciationDepletionAndAmortization")
               or _ttm(ticker, asof, "Depreciation"))

    # Year-ago revenue for growth
    revenue_yago = _ttm_revenue(ticker, asof - pd.Timedelta(days=365))
    revenue_growth = None
    if ttm_revenue and revenue_yago and revenue_yago > 0:
        revenue_growth = (ttm_revenue / revenue_yago) - 1.0

    ni_yago = _ttm(ticker, asof - pd.Timedelta(days=365), "NetIncomeLoss")
    earnings_growth = None
    if ttm_net_income is not None and ni_yago is not None and ni_yago != 0:
        earnings_growth = (ttm_net_income / abs(ni_yago)) - (1.0 if ni_yago > 0 else -1.0)

    assets = (bs.get("Assets") or {}).get("value")
    equity = (bs.get("StockholdersEquity") or {}).get("value")
    liab = (bs.get("Liabilities") or {}).get("value")
    cur_assets = (bs.get("AssetsCurrent") or {}).get("value")
    cur_liab = (bs.get("LiabilitiesCurrent") or {}).get("value")
    lt_debt = ((bs.get("LongTermDebt") or {}).get("value")
               or (bs.get("LongTermDebtNoncurrent") or {}).get("value"))
    cash = (bs.get("CashAndCashEquivalentsAtCarryingValue") or {}).get("value")
    shares_out = (bs.get("CommonStockSharesOutstanding") or {}).get("value")

    # Profitability ratios
    f["roa_ttm"] = (ttm_net_income / assets) if (ttm_net_income and assets) else None
    f["roe_ttm"] = (ttm_net_income / equity) if (ttm_net_income and equity and equity > 0) else None
    f["op_margin"] = (ttm_op_income / ttm_revenue) if (ttm_op_income and ttm_revenue and ttm_revenue > 0) else None
    f["gross_margin"] = (ttm_gp / ttm_revenue) if (ttm_gp and ttm_revenue and ttm_revenue > 0) else None
    f["net_margin"] = (ttm_net_income / ttm_revenue) if (ttm_net_income and ttm_revenue and ttm_revenue > 0) else None

    # Leverage / liquidity
    f["debt_to_equity"] = (lt_debt / equity) if (lt_debt and equity and equity > 0) else None
    f["liab_to_assets"] = (liab / assets) if (liab and assets) else None
    f["current_ratio"] = (cur_assets / cur_liab) if (cur_assets and cur_liab and cur_liab > 0) else None
    f["cash_ratio"] = (cash / cur_liab) if (cash and cur_liab and cur_liab > 0) else None

    # Efficiency
    f["asset_turnover"] = (ttm_revenue / assets) if (ttm_revenue and assets and assets > 0) else None

    # Quality / cash
    f["fcf_ttm"] = (ttm_ocf - ttm_capex) if (ttm_ocf is not None and ttm_capex is not None) else None
    f["accruals"] = ((ttm_net_income - ttm_ocf) / assets) if (
        ttm_net_income is not None and ttm_ocf is not None and assets and assets > 0
    ) else None

    # Growth
    f["revenue_growth_yoy"] = revenue_growth
    f["earnings_growth_yoy"] = earnings_growth

    # Raw stocks (used downstream for value ratios with price)
    f["__shares_out"] = shares_out
    f["__equity"] = equity
    f["__ttm_revenue"] = ttm_revenue
    f["__ttm_net_income"] = ttm_net_income
    f["__ttm_ocf"] = ttm_ocf
    f["__total_debt"] = lt_debt
    f["__cash"] = cash
    return f
