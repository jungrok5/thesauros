"""Ingest Korean corporate fundamentals from DART OpenAPI.

DART (전자공시 시스템) is the Korean equivalent of SEC EDGAR.
Free API key from https://opendart.fss.or.kr/

Scope (initial):
  - corpCode mapping (KRX 6-digit → DART corp_code)
  - 단일 회사 주요 재무지표 (fnlttSinglAcnt.json) — 연간 + 분기
  - 임원/주요주주 보유 변동 — for Korean insider-style signal

We store into the same `fundamentals` table by mapping concept names:

  DART 항목        →  XBRL-like concept
  매출액 / 영업수익  →  Revenues
  영업이익          →  OperatingIncomeLoss
  당기순이익        →  NetIncomeLoss
  자산총계          →  Assets
  부채총계          →  Liabilities
  자본총계          →  StockholdersEquity
  영업활동현금흐름  →  NetCashProvidedByUsedInOperatingActivities
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from app.config import DART_API_KEY, DART_BASE_URL
from app.data.pit_db import connect, cursor


# Account → XBRL-style concept mapping
DART_CONCEPT_MAP = {
    "매출액": "Revenues",
    "영업수익": "Revenues",
    "수익(매출액)": "Revenues",
    "매출총이익": "GrossProfit",
    "영업이익": "OperatingIncomeLoss",
    "영업이익(손실)": "OperatingIncomeLoss",
    "당기순이익": "NetIncomeLoss",
    "당기순이익(손실)": "NetIncomeLoss",
    "자산총계": "Assets",
    "유동자산": "AssetsCurrent",
    "부채총계": "Liabilities",
    "유동부채": "LiabilitiesCurrent",
    "자본총계": "StockholdersEquity",
    "영업활동으로인한현금흐름": "NetCashProvidedByUsedInOperatingActivities",
    "영업활동현금흐름": "NetCashProvidedByUsedInOperatingActivities",
}


def _ticker_market_lookup(stock_code: str) -> Optional[str]:
    """🚨 Bug #4 fix: stock_code → real ticker (with .KS or .KQ).

    Lookup which market the code actually exists in `prices` table.
    Returns None if neither exists.
    """
    from app.data.pit_db import cursor
    with cursor() as con:
        # Try KOSPI first (more common for blue chips)
        for suffix in (".KS", ".KQ"):
            r = con.execute(
                "SELECT 1 FROM prices WHERE ticker = ? LIMIT 1",
                [f"{stock_code}{suffix}"],
            ).fetchone()
            if r:
                return f"{stock_code}{suffix}"
    return None


def _have_key() -> bool:
    return bool(DART_API_KEY)


def fetch_corp_code_map() -> pd.DataFrame:
    """Download the full corpCode.xml zip and return (corp_code, stock_code, name).

    Cached on first call into models_store/dart_corp_code.parquet.
    """
    from pathlib import Path
    from io import BytesIO
    import zipfile
    import xml.etree.ElementTree as ET
    from app.config import MODEL_DIR

    cache = MODEL_DIR / "dart_corp_code.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    if not _have_key():
        raise RuntimeError("DART_API_KEY not set.")

    url = f"{DART_BASE_URL}/corpCode.xml?crtfc_key={DART_API_KEY}"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    with zipfile.ZipFile(BytesIO(res.content)) as z:
        with z.open("CORPCODE.xml") as f:
            tree = ET.parse(f)
    rows = []
    for el in tree.getroot().findall("list"):
        corp_code = el.findtext("corp_code", "")
        stock_code = el.findtext("stock_code", "") or ""
        name = el.findtext("corp_name", "")
        rows.append({
            "corp_code": corp_code.strip(),
            "stock_code": stock_code.strip(),
            "corp_name": name.strip(),
        })
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    return df


def _fetch_financials(corp_code: str, year: int, report_code: str = "11011"
                      ) -> List[Dict]:
    """Fetch one company's financials for a year.

    report_code:
      11011 = 사업보고서 (annual)
      11012 = 반기보고서 (semi-annual)
      11013 = 1분기, 11014 = 3분기
    """
    if not _have_key():
        raise RuntimeError("DART_API_KEY not set.")
    url = f"{DART_BASE_URL}/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report_code,
    }
    r = requests.get(url, params=params, timeout=15)
    if not r.ok:
        return []
    j = r.json()
    if j.get("status") != "000":
        return []
    return j.get("list", [])


def ingest_company(corp_code: str, stock_code: str,
                   years: List[int]) -> int:
    """Pull multi-year financials, store into fundamentals table."""
    if not stock_code:
        return 0

    ticker_kospi = f"{stock_code}.KS"
    ticker_kosdaq = f"{stock_code}.KQ"

    rows = []
    for y in years:
        for rc in ("11011",):  # annual only — quarterly is fnlttSinglAcntAll
            items = _fetch_financials(corp_code, y, rc)
            for item in items:
                concept_kr = (item.get("account_nm") or "").strip()
                concept = DART_CONCEPT_MAP.get(concept_kr)
                if not concept:
                    continue
                # Determine which statement segment
                consolidated = item.get("fs_div") == "CFS"  # 연결재무
                if not consolidated:
                    continue  # prefer consolidated
                val_str = (item.get("thstrm_amount") or "").replace(",", "")
                if not val_str or val_str in ("-", ""):
                    continue
                try:
                    value = float(val_str)
                except ValueError:
                    continue
                rcept = item.get("rcept_no") or ""
                # rcept_no's first 8 chars are filing date YYYYMMDD
                filed_date = None
                if len(rcept) >= 8:
                    try:
                        filed_date = pd.to_datetime(rcept[:8],
                                                     format="%Y%m%d").date()
                    except Exception:
                        filed_date = None
                # Period end: 12-31 for annual
                period_end = pd.Timestamp(f"{y}-12-31").date()
                # 🚨 Bug #10 fix: when filed_date is unknown, do NOT fall
                # back to period_end (12/31) — that fakes a same-day filing
                # and leaks 90-120 days of look-ahead. KR 사업보고서 is
                # legally filed within 90 days of year-end (~3/31). Use
                # period_end + 90 days as the conservative PIT default.
                if filed_date is None:
                    filed_date = (pd.Timestamp(period_end)
                                  + pd.Timedelta(days=90)).date()

                # 🚨 Bug #4 fix: lookup market from `prices` table (which one
                # actually exists). Avoids cross-contamination if same 6-digit
                # code happens to exist in both KOSPI and KOSDAQ historically.
                real_ticker = _ticker_market_lookup(stock_code)
                if not real_ticker:
                    # No prices for either — skip (don't pollute fundamentals)
                    continue
                rows.append({
                    "ticker": real_ticker,
                    "concept": concept,
                    "period_end": period_end,
                    "fp": "FY",
                    "fy": y,
                    "filed_date": filed_date,
                    "value": value,
                    "unit": "KRW",
                })

    if not rows:
        return 0
    df = pd.DataFrame(rows)
    con = connect()
    try:
        con.register("df_in", df)
        con.execute("""
            INSERT OR REPLACE INTO fundamentals
              (ticker, concept, period_end, fp, fy, filed_date, value, unit)
            SELECT ticker, concept, period_end, fp, fy, filed_date, value, unit
            FROM df_in
        """)
    finally:
        con.close()
    return len(rows)


def ingest_universe(stock_codes: Optional[List[str]] = None,
                    years: Optional[List[int]] = None,
                    verbose: bool = True) -> Dict[str, int]:
    """Ingest fundamentals for the listed stock_codes (or all currently in DB).

    Uses cached corp_code map.
    """
    if not _have_key():
        raise RuntimeError(
            "DART_API_KEY not set. Register at https://opendart.fss.or.kr/ "
            "and add to .env."
        )

    map_df = fetch_corp_code_map()
    map_df = map_df[map_df["stock_code"].str.match(r"^\d{6}$", na=False)]

    if stock_codes is None:
        # All KRX stocks already in `prices` table
        with cursor() as con:
            stock_codes = [
                r[0].split(".")[0] for r in con.execute(
                    "SELECT DISTINCT ticker FROM prices "
                    "WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
                ).fetchall()
            ]

    years = years or list(range(2018, 2026))
    counts: Dict[str, int] = {}
    n_done = 0
    for sc in stock_codes:
        matches = map_df[map_df["stock_code"] == sc]
        if matches.empty:
            counts[sc] = 0
            continue
        corp_code = matches.iloc[0]["corp_code"]
        try:
            n = ingest_company(corp_code, sc, years)
        except Exception as e:
            if verbose:
                print(f"  [{sc}] {e}")
            n = -1
        counts[sc] = n
        n_done += 1
        if verbose and n_done % 25 == 0:
            ok = sum(1 for v in counts.values() if v > 0)
            print(f"  ... {n_done}/{len(stock_codes)} done, {ok} got data")
        # DART has 1000 req/min; we go well under that
        time.sleep(0.06)

    return counts
