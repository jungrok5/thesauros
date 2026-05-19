"""SEC EDGAR ingest — US companies' fundamentals + filings (disclosures).

Mirrors what `app.data.ingest_dart` does for KR companies. Both write to
the same Supabase tables (`fundamentals`, `disclosures`) using the same
SEC-style concept names (DART maps Korean account names → us-gaap
concepts in `DART_CONCEPT_MAP`), so the downstream eval pipeline
(`app.db.eval_financials`) and the web UI work for KR + US transparently.

Endpoints (all free, no API key — SEC fair-use requires a User-Agent):
  - https://www.sec.gov/files/company_tickers.json
      → ticker ↔ CIK map (refreshed daily by SEC).
  - https://data.sec.gov/api/xbrl/companyfacts/CIK{padded10}.json
      → ALL XBRL concepts ever filed by that issuer.
  - https://data.sec.gov/submissions/CIK{padded10}.json
      → "recent" filings (forms 10-K, 10-Q, 8-K, S-1, ...).

Rate limit: SEC fair-use = 10 req/sec from one IP. We sleep 0.15 s
between requests to stay well under that.

Usage:
    python -m app.data.ingest_sec                # all US tickers
    python -m app.data.ingest_sec --tickers AAPL MSFT
    python -m app.data.ingest_sec --filings-only # disclosures, no fundamentals
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.config import SEC_USER_AGENT  # noqa: E402
from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_sec")

_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept": "application/json",
}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dash}/{doc}"
_SEC_RATE_SLEEP = 0.15  # 1/0.15 ≈ 6.6 req/s, comfortably under 10/s cap

# XBRL concepts we want in `fundamentals`. Each fact row is keyed by
# (ticker, concept, fy). The eval pipeline picks the canonical name via
# REVENUE_ALIASES etc.; we just need to populate any of them per FY.
TARGET_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "GrossProfit",
    "CostOfRevenue",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "Assets",
    "AssetsCurrent",
    "Liabilities",
    "LiabilitiesCurrent",
    "StockholdersEquity",
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
)

# Forms worth surfacing to users. Annual + quarterly reports + material
# events + IPO/registration. Exclude routine Form 4 (insider trades) and
# tiny notices that would flood the disclosures tab.
TARGET_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A",
    "8-K", "8-K/A",
    "20-F", "20-F/A",
    "40-F", "40-F/A",
    "S-1", "S-1/A",
    "DEF 14A",  # proxy
    "6-K",      # foreign issuers' material info
}

# Map SEC form code → human-readable Korean label so disclosures look
# consistent with DART's `report_type`. Anything not mapped falls back
# to the raw form code (still useful — "8-K" is widely understood).
_FORM_LABEL = {
    "10-K": "연간보고서 (10-K)",
    "10-K/A": "연간보고서 정정 (10-K/A)",
    "10-Q": "분기보고서 (10-Q)",
    "10-Q/A": "분기보고서 정정 (10-Q/A)",
    "8-K": "주요사항 (8-K)",
    "8-K/A": "주요사항 정정 (8-K/A)",
    "20-F": "해외 연간 (20-F)",
    "20-F/A": "해외 연간 정정 (20-F/A)",
    "40-F": "캐나다 연간 (40-F)",
    "40-F/A": "캐나다 연간 정정 (40-F/A)",
    "S-1": "신주발행 (S-1)",
    "S-1/A": "신주발행 정정 (S-1/A)",
    "DEF 14A": "주총소집 (DEF 14A)",
    "6-K": "해외 분기/주요사항 (6-K)",
}


# ---------------------------------------------------------------------
# CIK lookup
# ---------------------------------------------------------------------

def fetch_ticker_to_cik() -> Dict[str, str]:
    """Return {TICKER: "0000320193"-style padded CIK}. SEC publishes the
    full list as one JSON file — refresh daily, no need to query per row.
    """
    res = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=30)
    res.raise_for_status()
    payload = res.json()
    # SEC's format: { "0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ... }
    out: Dict[str, str] = {}
    for v in payload.values():
        t = str(v.get("ticker", "")).upper()
        cik = v.get("cik_str")
        if not t or cik is None:
            continue
        out[t] = str(cik).zfill(10)
    return out


# ---------------------------------------------------------------------
# Fundamentals (companyfacts)
# ---------------------------------------------------------------------

def fetch_company_facts(cik: str, retries: int = 3) -> dict:
    url = _COMPANYFACTS_URL.format(cik=cik)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return {}
            time.sleep(1.5 * (attempt + 1))
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    return {}


def _extract_annual_facts(
    facts_payload: dict,
) -> List[Tuple[str, int, float, str, Optional[date]]]:
    """Walk companyfacts JSON → list of (concept, fy, value, unit, filed_date).

    SEC structure:
        facts.us-gaap.<Concept>.units.<USD|shares|...>[] = {
            end: "2024-12-31", val: 391035000000, accn: "...",
            fy: 2024, fp: "FY", form: "10-K", filed: "2025-...",
        }

    We keep `fp == "FY"` only — quarterly rows duplicate annual sums and
    would confuse the year-over-year derivations downstream.
    """
    rows: List[Tuple[str, int, float, str, Optional[date]]] = []
    facts = ((facts_payload or {}).get("facts") or {}).get("us-gaap") or {}
    for concept, body in facts.items():
        if concept not in TARGET_CONCEPTS:
            continue
        units = (body or {}).get("units") or {}
        for unit_key, observations in units.items():
            # Prefer USD; for share counts SEC uses "shares". Skip exotic
            # units like "USD/shares" — those are EPS, not raw values.
            if unit_key not in ("USD", "shares"):
                continue
            for ob in observations or []:
                if ob.get("fp") != "FY":
                    continue
                fy = ob.get("fy")
                val = ob.get("val")
                if fy is None or val is None:
                    continue
                try:
                    fy_int = int(fy)
                    val_f = float(val)
                except (TypeError, ValueError):
                    continue
                filed_str = ob.get("filed") or ""
                filed_d: Optional[date] = None
                if filed_str:
                    try:
                        filed_d = date.fromisoformat(filed_str)
                    except ValueError:
                        filed_d = None
                rows.append((concept, fy_int, val_f, unit_key, filed_d))
    return rows


def _upsert_fundamentals(
    ticker: str,
    facts: Iterable[Tuple[str, int, float, str, Optional[date]]],
) -> int:
    # Dedupe by (concept, fy) — pick latest filed_date if multiple
    # observations exist (XBRL has restatements: same fy filed twice with
    # corrections). Without this we'd be at the mercy of dict ordering.
    best: Dict[Tuple[str, int], Tuple[float, str, Optional[date]]] = {}
    for concept, fy, val, unit, filed in facts:
        key = (concept, fy)
        cur = best.get(key)
        if cur is None:
            best[key] = (val, unit, filed)
            continue
        cur_filed = cur[2] or date.min
        new_filed = filed or date.min
        if new_filed > cur_filed:
            best[key] = (val, unit, filed)
    if not best:
        return 0
    period_end_by_fy: Dict[int, date] = {}
    payload = []
    for (concept, fy), (val, unit, filed) in best.items():
        # XBRL doesn't always give period_end on the FY row in the same
        # shape; use Dec-31 of fy as a stable fallback — same convention
        # the DART path uses.
        period_end = period_end_by_fy.setdefault(fy, date(fy, 12, 31))
        # If SEC didn't provide a filed date, fall back to period_end +
        # 90 days (typical 10-K filing window) so the row still has a PIT
        # anchor — matches the DART bug #10 fix in ingest_dart.py.
        if filed is None:
            try:
                filed_safe = date(fy + 1, 3, 31)
            except ValueError:
                filed_safe = period_end
        else:
            filed_safe = filed
        payload.append(
            (ticker, concept, fy, period_end, filed_safe, val, unit)
        )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO fundamentals
                  (ticker, concept, fy, period_end, filed_date, value, unit)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, concept, fy) DO UPDATE SET
                  period_end = EXCLUDED.period_end,
                  filed_date = EXCLUDED.filed_date,
                  value = EXCLUDED.value,
                  unit = EXCLUDED.unit
                """,
                payload,
            )
    return len(payload)


# ---------------------------------------------------------------------
# Disclosures (submissions API)
# ---------------------------------------------------------------------

def fetch_submissions(cik: str, retries: int = 3) -> dict:
    url = _SUBMISSIONS_URL.format(cik=cik)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return {}
            time.sleep(1.5 * (attempt + 1))
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    return {}


def _extract_recent_filings(
    submissions: dict,
    cik: str,
    limit: int = 30,
) -> List[Tuple[str, str, str, Optional[date], str]]:
    """Return [(rcept_no, report_nm, report_type, filed_date, url)].

    Submissions schema's `filings.recent` is parallel arrays — same index
    across `form`, `accessionNumber`, `filingDate`, `primaryDocument`.
    `accessionNumber` like "0000320193-25-000123" → `rcept_no` (unique
    PK in our `disclosures` table).
    """
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accns = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    docs = recent.get("primaryDocument") or []
    cik_int = int(cik)

    out: List[Tuple[str, str, str, Optional[date], str]] = []
    for i in range(min(len(forms), len(accns), len(dates), len(docs))):
        form = forms[i]
        if form not in TARGET_FORMS:
            continue
        accn = accns[i]
        filed_str = dates[i]
        doc = docs[i] or ""
        filed_d: Optional[date] = None
        if filed_str:
            try:
                filed_d = date.fromisoformat(filed_str)
            except ValueError:
                filed_d = None
        url = _FILING_URL.format(
            cik_int=cik_int,
            acc_no_dash=accn.replace("-", ""),
            doc=doc,
        )
        label = _FORM_LABEL.get(form, form)
        out.append((accn, label, form, filed_d, url))
        if len(out) >= limit:
            break
    return out


def _upsert_disclosures(
    ticker: str,
    filings: Iterable[Tuple[str, str, str, Optional[date], str]],
) -> int:
    payload = [
        (ticker, accn, name, ftype, fdate, url)
        for accn, name, ftype, fdate, url in filings
    ]
    if not payload:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO disclosures
                  (ticker, rcept_no, report_nm, report_type, filed_date, url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rcept_no) DO UPDATE SET
                  ticker = EXCLUDED.ticker,
                  report_nm = EXCLUDED.report_nm,
                  report_type = EXCLUDED.report_type,
                  filed_date = EXCLUDED.filed_date,
                  url = EXCLUDED.url
                """,
                payload,
            )
    return len(payload)


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def _us_tickers_from_db() -> List[str]:
    """Pull all US tickers from Supabase `tickers`. US = no .KS/.KQ suffix
    and market in known US exchanges (NYSE, NASDAQ, NYSEARCA, AMEX, etc.).
    """
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticker FROM tickers
                WHERE is_active = true
                  AND ticker NOT LIKE '%.KS'
                  AND ticker NOT LIKE '%.KQ'
                  AND (market IS NULL OR market NOT IN ('KOSPI', 'KOSDAQ'))
                """
            )
            return [r[0] for r in cur.fetchall()]


def ingest_one(
    ticker: str,
    ticker_to_cik: Dict[str, str],
    do_facts: bool = True,
    do_filings: bool = True,
) -> Dict[str, int]:
    """Fetch + upsert one US ticker. Returns counts per channel."""
    cik = ticker_to_cik.get(ticker.upper())
    if not cik:
        return {"facts": 0, "filings": 0}

    counts = {"facts": 0, "filings": 0}
    if do_facts:
        payload = fetch_company_facts(cik)
        time.sleep(_SEC_RATE_SLEEP)
        if payload:
            counts["facts"] = _upsert_fundamentals(
                ticker, _extract_annual_facts(payload)
            )
    if do_filings:
        subs = fetch_submissions(cik)
        time.sleep(_SEC_RATE_SLEEP)
        if subs:
            counts["filings"] = _upsert_disclosures(
                ticker, _extract_recent_filings(subs, cik)
            )
    return counts


def ingest_universe(
    tickers: Optional[List[str]] = None,
    do_facts: bool = True,
    do_filings: bool = True,
    verbose: bool = True,
) -> Dict[str, Dict[str, int]]:
    """Ingest US fundamentals + filings for all listed tickers (or all
    US tickers in the master). Returns {ticker: {facts, filings}}.
    """
    ticker_to_cik = fetch_ticker_to_cik()
    time.sleep(_SEC_RATE_SLEEP)
    if tickers is None:
        tickers = _us_tickers_from_db()

    results: Dict[str, Dict[str, int]] = {}
    n_done = 0
    for t in tickers:
        try:
            counts = ingest_one(t, ticker_to_cik, do_facts, do_filings)
        except Exception as e:
            if verbose:
                print(f"  [{t}] ERROR: {e}")
            counts = {"facts": -1, "filings": -1}
        results[t] = counts
        n_done += 1
        if verbose and (n_done % 25 == 0 or n_done == len(tickers)):
            ok_facts = sum(1 for v in results.values() if v["facts"] > 0)
            ok_files = sum(1 for v in results.values() if v["filings"] > 0)
            print(
                f"  ... {n_done}/{len(tickers)} done, "
                f"facts {ok_facts}, filings {ok_files}"
            )
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SEC EDGAR ingest")
    parser.add_argument("--tickers", nargs="*", default=None,
                        help="Specific US tickers (default: all in DB)")
    parser.add_argument("--filings-only", action="store_true",
                        help="Skip companyfacts, only fetch submissions")
    parser.add_argument("--facts-only", action="store_true",
                        help="Skip submissions, only fetch companyfacts")
    args = parser.parse_args(argv)

    do_facts = not args.filings_only
    do_filings = not args.facts_only

    counts = ingest_universe(
        tickers=args.tickers,
        do_facts=do_facts,
        do_filings=do_filings,
    )
    ok_facts = sum(1 for v in counts.values() if v["facts"] > 0)
    ok_files = sum(1 for v in counts.values() if v["filings"] > 0)
    total_fact_rows = sum(max(0, v["facts"]) for v in counts.values())
    total_file_rows = sum(max(0, v["filings"]) for v in counts.values())
    print(
        f"\nDone: {len(counts)} tickers, "
        f"{ok_facts} got fundamentals ({total_fact_rows} rows), "
        f"{ok_files} got filings ({total_file_rows} rows)."
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
