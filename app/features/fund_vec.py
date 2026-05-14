"""Vectorized PIT fundamentals — all (ticker, asof) at once.

Strategy:
  1. Load entire fundamentals table once (1-2M rows fits easily in RAM).
  2. For each (ticker, asof), filter visible rows once via merge_asof.
  3. Compute features in pandas vectorized form.

Output: DataFrame indexed by (date, ticker) with one column per feature.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from app.data.pit_db import cursor

REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
ALL_CONCEPTS = REVENUE_CONCEPTS + [
    "NetIncomeLoss", "OperatingIncomeLoss", "GrossProfit",
    "Assets", "AssetsCurrent",
    "Liabilities", "LiabilitiesCurrent",
    "StockholdersEquity",
    "LongTermDebt", "LongTermDebtNoncurrent",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "DepreciationDepletionAndAmortization", "Depreciation",
    "CommonStockSharesOutstanding",
]


def _load_all() -> pd.DataFrame:
    with cursor() as con:
        df = con.execute(f"""
            SELECT ticker, concept, period_end, fp, fy, filed_date, value
            FROM fundamentals
            WHERE concept IN ({','.join(['?']*len(ALL_CONCEPTS))})
        """, ALL_CONCEPTS).df()
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["filed_date"] = pd.to_datetime(df["filed_date"])
    df = df.dropna(subset=["period_end", "filed_date"])
    return df


def _pit_latest(df: pd.DataFrame, asof_dates: pd.DatetimeIndex,
                concept: str, ttm: bool = False,
                rev_fallback: bool = False) -> pd.DataFrame:
    """For each (ticker × asof_date), pull latest visible value.

    If ttm=True, sum the 4 most-recent quarterly values. Falls back to FY
    value if Q1..Q4 not available.

    If rev_fallback=True, treat `concept` as a list and pick the first
    available concept per ticker.
    """
    # We rebuild a tidy dataframe sorted by (ticker, filed_date)
    if rev_fallback:
        # concept here is actually a list — pick first non-null per (ticker, period_end)
        sub = df[df["concept"].isin(concept)].copy()
        # Order so the preferred concept wins
        order_map = {c: i for i, c in enumerate(concept)}
        sub["_pref"] = sub["concept"].map(order_map)
        sub = sub.sort_values(["ticker", "period_end", "filed_date", "_pref"])
        sub = sub.drop_duplicates(subset=["ticker", "period_end", "filed_date"], keep="first")
    else:
        sub = df[df["concept"] == concept].copy()
    if sub.empty:
        return pd.DataFrame()
    # Drop period-end duplicates (amendments) — keep latest filed_date per period_end
    sub = sub.sort_values(["ticker", "period_end", "filed_date"])
    sub = sub.drop_duplicates(subset=["ticker", "period_end"], keep="last")

    if ttm:
        # For each (ticker, asof), take the 4 most-recent (period_end <= asof) Q rows
        # whose filed_date <= asof, sum their values.
        # Implement: for each ticker, build a long timeseries of quarterly values keyed
        # by period_end, then for each asof rolling-sum 4 most recent visible.
        # We process per-ticker using groupby + apply.
        results = []
        sub = sub[sub["fp"].isin(["Q1", "Q2", "Q3", "Q4", "FY"])]
        for tk, g in sub.groupby("ticker", sort=False):
            g = g.sort_values(["filed_date", "period_end"])
            # For every asof, find the latest 4 quarterly observations whose filed_date<=asof
            # Use searchsorted on filed_date.
            filed = g["filed_date"].values
            pe = g["period_end"].values
            vals = g["value"].values
            fps = g["fp"].values
            for asof in asof_dates:
                idx = np.searchsorted(filed, np.datetime64(asof), side="right")
                if idx == 0:
                    results.append((tk, asof, np.nan)); continue
                # Walk backwards collecting unique period_ends, prefer Q1..Q4
                pulled = []
                pulled_pe = set()
                fy_val = None
                fy_pe = None
                for j in range(idx - 1, -1, -1):
                    if pe[j] in pulled_pe:
                        continue
                    if fps[j] in ("Q1", "Q2", "Q3", "Q4"):
                        pulled.append(vals[j])
                        pulled_pe.add(pe[j])
                        if len(pulled) == 4:
                            break
                    elif fy_val is None and fps[j] == "FY":
                        fy_val = vals[j]; fy_pe = pe[j]
                if len(pulled) == 4:
                    results.append((tk, asof, float(np.sum(pulled))))
                elif fy_val is not None:
                    results.append((tk, asof, float(fy_val)))
                else:
                    results.append((tk, asof, np.nan))
        return pd.DataFrame(results, columns=["ticker", "asof", "value"])
    else:
        # Latest snapshot: for each (ticker, asof), latest period_end whose filed_date<=asof
        # We need filed_date too.
        # Sort by filed_date ascending
        sub = sub.sort_values(["ticker", "filed_date"])
        results = []
        for tk, g in sub.groupby("ticker", sort=False):
            filed = g["filed_date"].values
            pe = g["period_end"].values
            vals = g["value"].values
            for asof in asof_dates:
                idx = np.searchsorted(filed, np.datetime64(asof), side="right")
                if idx == 0:
                    results.append((tk, asof, np.nan))
                else:
                    # Among first `idx` rows, take the one with the latest period_end
                    sl = slice(0, idx)
                    j = sl.start + np.argmax(pe[sl])
                    results.append((tk, asof, float(vals[j])))
        return pd.DataFrame(results, columns=["ticker", "asof", "value"])


def build_fundamental_panel(asof_dates: pd.DatetimeIndex,
                            tickers: Optional[List[str]] = None,
                            include_yago: bool = False) -> pd.DataFrame:
    """Build a fundamental feature DataFrame for all (ticker × asof_date).

    If include_yago=True, also returns columns suffixed `_prev` representing
    the equivalent fundamental snapshot one year earlier (used for Piotroski
    YoY checks, Mohanram, Beneish proxies).
    """
    raw = _load_all()
    if tickers:
        raw = raw[raw["ticker"].isin(tickers)]
    if raw.empty:
        return pd.DataFrame()

    # Ensure asof dates are datetime
    asof_dates = pd.DatetimeIndex(asof_dates)

    # TTM flows
    rev = _pit_latest(raw, asof_dates, REVENUE_CONCEPTS, ttm=True, rev_fallback=True)
    rev_yago = _pit_latest(raw, asof_dates - pd.Timedelta(days=365),
                           REVENUE_CONCEPTS, ttm=True, rev_fallback=True)
    ni = _pit_latest(raw, asof_dates, "NetIncomeLoss", ttm=True)
    ni_yago = _pit_latest(raw, asof_dates - pd.Timedelta(days=365),
                          "NetIncomeLoss", ttm=True)
    op = _pit_latest(raw, asof_dates, "OperatingIncomeLoss", ttm=True)
    gp = _pit_latest(raw, asof_dates, "GrossProfit", ttm=True)
    ocf = _pit_latest(raw, asof_dates,
                      "NetCashProvidedByUsedInOperatingActivities", ttm=True)
    capex = _pit_latest(raw, asof_dates,
                        "PaymentsToAcquirePropertyPlantAndEquipment", ttm=True)

    # Stocks (latest snapshot)
    assets = _pit_latest(raw, asof_dates, "Assets")
    cur_assets = _pit_latest(raw, asof_dates, "AssetsCurrent")
    liab = _pit_latest(raw, asof_dates, "Liabilities")
    cur_liab = _pit_latest(raw, asof_dates, "LiabilitiesCurrent")
    equity = _pit_latest(raw, asof_dates, "StockholdersEquity")
    lt_debt = _pit_latest(raw, asof_dates, "LongTermDebt")
    lt_debt_nc = _pit_latest(raw, asof_dates, "LongTermDebtNoncurrent")
    cash = _pit_latest(raw, asof_dates, "CashAndCashEquivalentsAtCarryingValue")
    shares = _pit_latest(raw, asof_dates, "CommonStockSharesOutstanding")

    # Restructure each into wide form on (asof, ticker)
    def _w(df, name):
        if df is None or df.empty:
            return pd.DataFrame()
        return df.rename(columns={"asof": "date", "value": name})

    out = _w(rev, "ttm_revenue")
    for name, df in [
        ("ttm_revenue_yago", rev_yago), ("ttm_ni", ni), ("ttm_ni_yago", ni_yago),
        ("ttm_op", op), ("ttm_gp", gp), ("ttm_ocf", ocf), ("ttm_capex", capex),
        ("assets", assets), ("cur_assets", cur_assets),
        ("liabilities", liab), ("cur_liab", cur_liab),
        ("equity", equity), ("lt_debt", lt_debt), ("lt_debt_nc", lt_debt_nc),
        ("cash", cash), ("shares_out", shares),
    ]:
        w = _w(df, name)
        if not w.empty:
            out = out.merge(w, on=["date", "ticker"], how="outer")
    if out.empty:
        return out

    # Derived ratios
    out["roa_ttm"] = out["ttm_ni"] / out["assets"]
    out["roe_ttm"] = np.where(out["equity"] > 0, out["ttm_ni"] / out["equity"], np.nan)
    out["op_margin"] = out["ttm_op"] / out["ttm_revenue"]
    out["gross_margin"] = out["ttm_gp"] / out["ttm_revenue"]
    out["net_margin"] = out["ttm_ni"] / out["ttm_revenue"]
    debt = out["lt_debt"].fillna(out["lt_debt_nc"])
    out["debt_to_equity"] = np.where(out["equity"] > 0, debt / out["equity"], np.nan)
    out["liab_to_assets"] = out["liabilities"] / out["assets"]
    out["current_ratio"] = np.where(out["cur_liab"] > 0,
                                    out["cur_assets"] / out["cur_liab"], np.nan)
    out["cash_ratio"] = np.where(out["cur_liab"] > 0, out["cash"] / out["cur_liab"], np.nan)
    out["asset_turnover"] = np.where(out["assets"] > 0,
                                     out["ttm_revenue"] / out["assets"], np.nan)
    out["fcf_ttm"] = out["ttm_ocf"] - out["ttm_capex"]
    out["accruals"] = np.where(out["assets"] > 0,
                               (out["ttm_ni"] - out["ttm_ocf"]) / out["assets"], np.nan)

    # Growth
    out["revenue_growth_yoy"] = np.where(
        out["ttm_revenue_yago"] > 0,
        (out["ttm_revenue"] / out["ttm_revenue_yago"]) - 1.0, np.nan,
    )
    out["earnings_growth_yoy"] = np.where(
        out["ttm_ni_yago"].abs() > 0,
        (out["ttm_ni"] - out["ttm_ni_yago"]) / out["ttm_ni_yago"].abs(),
        np.nan,
    )

    # Keep raw stocks too for valuation in the panel (joined w/ price later)
    out["__shares_out"] = out["shares_out"]
    out["__equity"] = out["equity"]
    out["__ttm_revenue"] = out["ttm_revenue"]
    out["__ttm_ni"] = out["ttm_ni"]
    out["__total_debt"] = debt
    out["__cash"] = out["cash"]

    if include_yago:
        # Year-ago snapshot of stocks for YoY checks (Piotroski etc.)
        prev_dates = asof_dates - pd.Timedelta(days=365)
        prev_assets = _pit_latest(raw, prev_dates, "Assets")
        prev_cur_assets = _pit_latest(raw, prev_dates, "AssetsCurrent")
        prev_cur_liab = _pit_latest(raw, prev_dates, "LiabilitiesCurrent")
        prev_equity = _pit_latest(raw, prev_dates, "StockholdersEquity")
        prev_lt_debt = _pit_latest(raw, prev_dates, "LongTermDebt")
        prev_shares = _pit_latest(raw, prev_dates, "CommonStockSharesOutstanding")
        prev_gp = _pit_latest(raw, prev_dates, "GrossProfit", ttm=True)
        prev_ocf = _pit_latest(raw, prev_dates,
                               "NetCashProvidedByUsedInOperatingActivities", ttm=True)

        # Map prev_dates back to asof_dates
        date_map = pd.Series(asof_dates, index=prev_dates)

        for name, df in [
            ("assets_prev", prev_assets), ("cur_assets_prev", prev_cur_assets),
            ("cur_liab_prev", prev_cur_liab), ("equity_prev", prev_equity),
            ("lt_debt_prev", prev_lt_debt), ("shares_out_prev", prev_shares),
            ("ttm_gp_prev", prev_gp), ("ttm_ocf_prev", prev_ocf),
        ]:
            if df is None or df.empty:
                continue
            df2 = df.rename(columns={"value": name})
            # Translate asof (which is prev_dates here) back to current asof_dates
            df2["asof"] = df2["asof"].map(date_map)
            df2 = df2.rename(columns={"asof": "date"}).dropna(subset=["date"])
            out = out.merge(df2, on=["date", "ticker"], how="left")

    return out
