"""Build the S&P 500 universe with ticker → CIK mapping.

Sources (all free, no API key):
  - Wikipedia "List of S&P 500 companies" — current constituents + GICS sector
  - SEC company_tickers.json — ticker → CIK
"""
from __future__ import annotations

import io
import time
from typing import List, Tuple

import pandas as pd
import requests

from app.config import SEC_USER_AGENT
from app.data.pit_db import cursor, set_meta

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
    """Returns {ticker_upper: cik_zfill10} from SEC's master mapping."""
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


def build_universe(verbose: bool = True) -> int:
    """Populate the `universe` table. Returns number of rows."""
    sp = fetch_sp500_table()
    # SEC mapping uses dot-style (BRK.B) — let's keep both shapes.
    sec_map = fetch_sec_ticker_to_cik()
    rows: List[Tuple] = []
    for _, r in sp.iterrows():
        t = r["ticker"]
        # SEC uses no hyphen — try both forms
        cik = sec_map.get(t.replace("-", "")) or sec_map.get(t.replace("-", "."))
        rows.append((
            t, cik, r["name"], r["sector"], r["sub_industry"],
            r["added_date"].date() if pd.notna(r["added_date"]) else None,
            True,
        ))
    with cursor() as con:
        con.execute("DELETE FROM universe")
        con.executemany(
            "INSERT INTO universe(ticker, cik, name, sector, gics_industry, added_date, is_active)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    set_meta("universe.last_built", time.strftime("%Y-%m-%dT%H:%M:%S"))
    if verbose:
        with cursor() as con:
            n_total = con.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
            n_with_cik = con.execute(
                "SELECT COUNT(*) FROM universe WHERE cik IS NOT NULL"
            ).fetchone()[0]
            print(f"[universe] inserted {n_total} rows ({n_with_cik} with CIK)")
    return len(rows)


def get_active_tickers(with_cik_only: bool = True) -> List[str]:
    with cursor() as con:
        q = "SELECT ticker FROM universe WHERE is_active"
        if with_cik_only:
            q += " AND cik IS NOT NULL"
        q += " ORDER BY ticker"
        return [r[0] for r in con.execute(q).fetchall()]


def get_universe_df() -> pd.DataFrame:
    with cursor() as con:
        return con.execute("SELECT * FROM universe ORDER BY ticker").df()
