"""S&P 500 constituent fetch — used by app.db.seed_tickers for the US side.

Historical context: this module also used to ingest into the local DuckDB
`universe` table (build_universe / get_active_tickers / get_universe_df).
After the pivot to a Supabase-backed site the live data path is the
`tickers` table in Supabase, populated by app.db.seed_tickers from Wikipedia
(this module) + Nasdaq Trader symbol files. The DuckDB-bound helpers were
removed.
"""
from __future__ import annotations

import io
from typing import List, Tuple

import pandas as pd
import requests

from app.config import SEC_USER_AGENT

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"

_HEADERS_WIKI = {"User-Agent": "Mozilla/5.0 (research)"}
_HEADERS_SEC = {"User-Agent": SEC_USER_AGENT}


def fetch_sp500_table() -> pd.DataFrame:
    """Returns DataFrame with columns: ticker, name, sector, sub_industry, added_date."""
    r = requests.get(WIKI_URL, headers=_HEADERS_WIKI, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    df = tables[0].copy()
    cols = {c: c.lower() for c in df.columns}
    df.rename(columns=cols, inplace=True)
    out = pd.DataFrame({
        "ticker": df["symbol"].astype(str).str.replace(".", "-", regex=False),
        "name": df["security"].astype(str),
        "sector": df["gics sector"].astype(str),
        "sub_industry": df["gics sub-industry"].astype(str),
        "added_date": pd.to_datetime(df.get("date added"), errors="coerce"),
    })
    return out.dropna(subset=["ticker"]).reset_index(drop=True)


def fetch_sec_ticker_to_cik() -> dict:
    """Returns {ticker_upper: cik_zfill10} from SEC's master mapping.

    Kept available because seed_tickers may eventually want CIK enrichment;
    currently unused by the cron path.
    """
    r = requests.get(SEC_TICKER_URL, headers=_HEADERS_SEC, timeout=30)
    r.raise_for_status()
    data = r.json()
    out = {}
    for _, row in data.items():
        t = str(row.get("ticker", "")).upper()
        cik = str(row.get("cik_str", "")).zfill(10)
        if t and cik:
            out[t] = cik
    return out
