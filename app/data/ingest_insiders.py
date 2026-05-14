"""Ingest insider transactions from SEC EDGAR Form 4 filings.

Form 4 reports purchases/sales by company officers, directors, and 10%+
shareholders. This is the **strongest free signal available to retail**:
multiple academic studies have documented +2-6% / year alpha from
cluster-buying signals (Lakonishok-Lee 2001, Cohen-Malloy-Pomorski 2012).

We pull each ticker's recent Form 4 submissions from EDGAR's
submissions API, parse the XML for transaction code, share count and
price, and store one row per transaction.

Schema (added to pit_db.py):

  insider_transactions(
    ticker, filed_date, txn_date, insider_name, insider_title,
    txn_code, txn_shares, txn_price_usd, ownership_after
  )

Transaction codes (subset):
  P = open-market purchase  ⭐ bullish
  S = open-market sale       ⭐ bearish
  A = grant/award (low signal)
  M = option exercise (low signal)
  F = tax withholding (low signal)

Higher-level features (computed in features/insider_features.py):
  insider_net_buy_90d, insider_buy_cluster, ceo_buy_30d, etc.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd
import requests
from tqdm import tqdm

from app.config import SEC_USER_AGENT
from app.data.pit_db import connect, cursor


_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def _throttle():
    """SEC fair-use: ≤10 req/sec. We use ~8/sec to be safe."""
    global _LAST_REQUEST
    with _RATE_LOCK:
        elapsed = time.time() - _LAST_REQUEST
        if elapsed < 0.125:
            time.sleep(0.125 - elapsed)
        _LAST_REQUEST = time.time()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
INSIDER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS insider_transactions (
    ticker            VARCHAR,
    cik               VARCHAR,
    filed_date        DATE,
    txn_date          DATE,
    insider_name      VARCHAR,
    insider_title     VARCHAR,
    txn_code          VARCHAR,
    txn_shares        DOUBLE,
    txn_price_usd     DOUBLE,
    ownership_after   DOUBLE,
    acquired_disposed VARCHAR,
    accession         VARCHAR,
    PRIMARY KEY (cik, accession, insider_name, txn_date, txn_code)
);
CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_transactions(ticker, filed_date);
"""


def ensure_schema() -> None:
    with cursor() as con:
        con.execute(INSIDER_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Filings list
# ---------------------------------------------------------------------------
def _list_form4_for_cik(cik: str, max_filings: int = 200) -> List[Dict]:
    """List the most recent Form 4 submissions for a CIK.

    Uses the EDGAR submissions API: /submissions/CIK{cik}.json
    """
    _throttle()
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    res = requests.get(url, headers=_HEADERS, timeout=15)
    if not res.ok:
        return []
    j = res.json()
    recent = j.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary = recent.get("primaryDocument", [])

    out = []
    for i in range(min(len(forms), max_filings * 5)):
        if forms[i] != "4":
            continue
        out.append({
            "form": forms[i],
            "accession": accessions[i],
            "filed_date": dates[i],
            "primary_doc": primary[i] if i < len(primary) else "",
        })
        if len(out) >= max_filings:
            break
    return out


# ---------------------------------------------------------------------------
# Form 4 XML parsing
# ---------------------------------------------------------------------------
def _form4_xml_url(cik: str, accession: str) -> str:
    """SEC stores docs under /Archives/edgar/data/<cik>/<accession-no-dashes>/."""
    acc_clean = accession.replace("-", "")
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}"
            f"/{acc_clean}/{accession}.txt")


def _form4_index_url(cik: str, accession: str) -> str:
    """Filing index page lists all docs in the submission."""
    acc_clean = accession.replace("-", "")
    return (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={int(cik)}&type=4&dateb=&owner=include&count=40")


def _fetch_form4_xml(cik: str, accession: str) -> Optional[str]:
    """Download the primary XML for a Form 4 filing.

    Tries the standard naming convention <accession>.xml first; falls back
    to scanning the filing's index page.
    """
    acc_clean = accession.replace("-", "")
    candidates = [
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
        f"{accession}.xml",
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
        f"primary_doc.xml",
    ]
    for url in candidates:
        _throttle()
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.ok and "<ownershipDocument" in r.text:
            return r.text
    # Fall back: scrape the index for any .xml
    _throttle()
    idx_url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{acc_clean}/")
    r = requests.get(idx_url, headers=_HEADERS, timeout=15)
    if r.ok:
        for m in re.findall(r'href="([^"]+\.xml)"', r.text):
            url = f"https://www.sec.gov{m}" if m.startswith("/") else idx_url + m
            _throttle()
            sub = requests.get(url, headers=_HEADERS, timeout=15)
            if sub.ok and "<ownershipDocument" in sub.text:
                return sub.text
    return None


def _parse_form4(xml: str) -> List[Dict]:
    """Extract transactions from a Form 4 XML document.

    Returns one dict per non-derivative transaction:
      insider_name, insider_title, txn_date, txn_code,
      txn_shares, txn_price_usd, acquired_disposed (A/D), ownership_after
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    # Insider name + title
    name_el = root.find("reportingOwner/reportingOwnerId/rptOwnerName")
    insider_name = name_el.text.strip() if name_el is not None and name_el.text else ""
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    title_parts = []
    if rel is not None:
        if rel.findtext("isDirector") in ("1", "true"):
            title_parts.append("Director")
        if rel.findtext("isOfficer") in ("1", "true"):
            t = rel.findtext("officerTitle") or "Officer"
            title_parts.append(t.strip())
        if rel.findtext("isTenPercentOwner") in ("1", "true"):
            title_parts.append("10%+ Owner")
    insider_title = " / ".join(title_parts)

    out = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        txn_date = txn.findtext("transactionDate/value", default="")
        coding = txn.find("transactionCoding")
        txn_code = coding.findtext("transactionCode", default="") if coding is not None else ""
        amt = txn.find("transactionAmounts")
        shares = amt.findtext("transactionShares/value", default="") if amt is not None else ""
        price = amt.findtext("transactionPricePerShare/value", default="") if amt is not None else ""
        ad = amt.findtext("transactionAcquiredDisposedCode/value", default="") if amt is not None else ""
        own = txn.find("postTransactionAmounts")
        own_after = own.findtext("sharesOwnedFollowingTransaction/value", default="") if own is not None else ""
        try:
            shares_f = float(shares) if shares else 0.0
            price_f = float(price) if price else 0.0
            own_f = float(own_after) if own_after else 0.0
        except ValueError:
            continue
        out.append({
            "insider_name": insider_name,
            "insider_title": insider_title,
            "txn_date": txn_date,
            "txn_code": txn_code,
            "txn_shares": shares_f,
            "txn_price_usd": price_f,
            "ownership_after": own_f,
            "acquired_disposed": ad,
        })
    return out


# ---------------------------------------------------------------------------
# Bulk ingest
# ---------------------------------------------------------------------------
def _ingest_one(ticker: str, cik: str,
                max_filings: int = 100) -> List[Dict]:
    """Fetch + parse Form 4 filings for a single CIK."""
    out: List[Dict] = []
    try:
        filings = _list_form4_for_cik(cik, max_filings=max_filings)
    except Exception:
        return out
    for f in filings:
        xml = _fetch_form4_xml(cik, f["accession"])
        if xml is None:
            continue
        for txn in _parse_form4(xml):
            out.append({
                "ticker": ticker,
                "cik": cik,
                "filed_date": f["filed_date"],
                "accession": f["accession"],
                **txn,
            })
    return out


def ingest_universe(tickers_cik: List[Dict], max_filings_per_ticker: int = 100,
                    workers: int = 4, verbose: bool = True) -> Dict[str, int]:
    """Bulk fetch insider transactions for a list of [{ticker, cik}] entries.

    Returns counts per ticker. SEC rate-limited internally.
    """
    ensure_schema()
    rows: List[Dict] = []
    counts: Dict[str, int] = {}

    pbar = tqdm(total=len(tickers_cik), desc="Form 4", disable=not verbose)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_ingest_one, t["ticker"], t["cik"],
                          max_filings_per_ticker): t["ticker"]
                for t in tickers_cik}
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                if verbose:
                    tqdm.write(f"  [{tk}] error: {e}")
                r = []
            counts[tk] = len(r)
            rows.extend(r)
            pbar.update(1)
    pbar.close()

    if not rows:
        return counts

    df = pd.DataFrame(rows)
    df["filed_date"] = pd.to_datetime(df["filed_date"]).dt.date
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce").dt.date
    df = df.dropna(subset=["txn_date", "txn_code"])

    if verbose:
        print(f"[insiders] inserting {len(df):,} rows ...")
    con = connect()
    try:
        con.register("df_in", df)
        con.execute("""
            INSERT OR REPLACE INTO insider_transactions
            (ticker, cik, filed_date, txn_date, insider_name, insider_title,
             txn_code, txn_shares, txn_price_usd, ownership_after,
             acquired_disposed, accession)
            SELECT ticker, cik, filed_date, txn_date, insider_name,
                   insider_title, txn_code, txn_shares, txn_price_usd,
                   ownership_after, acquired_disposed, accession FROM df_in
        """)
        if verbose:
            n = con.execute(
                "SELECT COUNT(*) FROM insider_transactions"
            ).fetchone()[0]
            print(f"[insiders] table now has {n:,} rows")
    finally:
        con.close()
    return counts


def ingest_universe_default(max_filings_per_ticker: int = 50,
                            workers: int = 4,
                            verbose: bool = True) -> Dict[str, int]:
    """Pull recent insider data for all S&P 500 tickers in universe table."""
    from app.data.universe import get_universe_df
    uni = get_universe_df()
    uni = uni[uni["cik"].notna() & (uni["cik"] != "")]
    targets = [{"ticker": r["ticker"], "cik": str(r["cik"]).strip()}
               for _, r in uni.iterrows()]
    return ingest_universe(targets, max_filings_per_ticker, workers, verbose)
