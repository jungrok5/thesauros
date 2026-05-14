"""Ingest SEC EDGAR Company Facts → DuckDB fundamentals table.

For each company (CIK), call:
    https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
which returns ALL XBRL concepts ever filed by that issuer, with the
"filed" date attached to every observation. That filed date is our
PIT timestamp — we only know value V for company C for period P
on or after `filed_date`.

We extract a curated set of high-information concepts (revenue, net
income, OCF, total assets, total liabilities, stockholders equity,
EPS diluted, shares outstanding, …).

SEC fair-use: at most 10 req/sec from one IP. Identify in User-Agent.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Tuple

import requests
from tqdm import tqdm

from app.config import SEC_USER_AGENT
from app.data.pit_db import connect, cursor

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Subset of us-gaap concepts we need for our features.
# More can be added later — keep narrow to control DB size + parsing time.
TARGET_CONCEPTS = {
    # Income statement
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "CostOfRevenue",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    # Balance sheet
    "Assets",
    "AssetsCurrent",
    "Liabilities",
    "LiabilitiesCurrent",
    "StockholdersEquity",
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "CashAndCashEquivalentsAtCarryingValue",
    # Cash flow
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "Depreciation",
    "DepreciationDepletionAndAmortization",
    # Shares
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
}


def fetch_company_facts(cik: str, max_retries: int = 3) -> dict:
    url = COMPANYFACTS_URL.format(cik=cik.zfill(10))
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return {}  # no XBRL data for this CIK
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return {}


def _extract_observations(facts: dict) -> List[Tuple]:
    """Yield rows (concept, period_end, fp, fy, filed_date, value, unit) from a
    company-facts payload. We pick every targeted concept; among multiple
    units we prefer USD where available, then per-share, then count.
    """
    rows: List[Tuple] = []
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for concept, body in us_gaap.items():
        if concept not in TARGET_CONCEPTS:
            continue
        units = body.get("units") or {}
        # Pick best unit: USD/USD-per-shares/shares
        preferred_unit = None
        for u in ("USD", "USD/shares", "shares"):
            if u in units:
                preferred_unit = u
                break
        if preferred_unit is None and units:
            preferred_unit = next(iter(units.keys()))
        if preferred_unit is None:
            continue
        for obs in units[preferred_unit]:
            rows.append((
                concept,
                obs.get("end"),     # period_end
                obs.get("fp"),
                obs.get("fy"),
                obs.get("filed"),   # filed_date — PIT key
                obs.get("val"),
                preferred_unit,
            ))
    return rows


def ingest_for_ticker(ticker: str, cik: str) -> int:
    """Fetch + insert one company's facts. Returns rows inserted.

    Uses a per-call connection — for the bulk path call ingest_universe()
    instead which reuses a single connection.
    """
    facts = fetch_company_facts(cik)
    if not facts:
        return 0
    obs = _extract_observations(facts)
    if not obs:
        return 0
    rows = [(ticker, *o) for o in obs]
    with cursor() as con:
        con.executemany(
            "INSERT OR REPLACE INTO fundamentals "
            "(ticker, concept, period_end, fp, fy, filed_date, value, unit) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


# Rate limit: SEC asks ≤10 req/s/IP. We aim for ~8/s with a token-bucket-like
# minimum spacing of 0.13s between request starts.
_rate_lock = threading.Lock()
_last_call = [0.0]


def _rate_throttle(min_gap: float = 0.13) -> None:
    with _rate_lock:
        now = time.monotonic()
        wait = min_gap - (now - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _fetch_with_throttle(ticker: str, cik: str):
    _rate_throttle()
    facts = fetch_company_facts(cik)
    if not facts:
        return ticker, []
    obs = _extract_observations(facts)
    return ticker, obs


def ingest_universe(tickers_and_ciks: Iterable[Tuple[str, str]],
                    sleep_s: float = 0.12,  # kept for backward compat (unused)
                    verbose: bool = True,
                    workers: int = 8) -> Dict[str, int]:
    """Bulk ingest: fetch in parallel, accumulate rows in memory, single bulk
    DataFrame insert at the end (DuckDB handles a 2M-row DataFrame insert in
    a few seconds — much faster than per-ticker executemany).
    """
    import pandas as pd

    pairs = [(t, c) for t, c in tickers_and_ciks if c]
    counts: Dict[str, int] = {}
    all_rows: List[tuple] = []

    pbar = tqdm(total=len(pairs), desc="SEC fetch", disable=not verbose)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch_with_throttle, t, c): t for t, c in pairs}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                _, obs = fut.result()
            except Exception as e:
                if verbose:
                    tqdm.write(f"  [{ticker}] fetch error: {e}")
                obs = []
            for o in obs:
                all_rows.append((ticker, *o))
            counts[ticker] = len(obs)
            pbar.update(1)
    pbar.close()

    if not all_rows:
        return counts

    if verbose:
        print(f"[SEC] fetched {len(all_rows):,} rows; bulk inserting…")

    df = pd.DataFrame(all_rows, columns=[
        "ticker", "concept", "period_end", "fp", "fy",
        "filed_date", "value", "unit",
    ])
    # Normalize dates
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce").dt.date
    df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce").dt.date
    df = df.dropna(subset=["period_end", "filed_date"])

    # DuckDB pandas registration → single bulk insert. Use INSERT OR REPLACE
    # via a CTE to handle the PK upsert.
    con = connect()
    try:
        con.register("df_in", df)
        # Drop duplicates within the batch first (PK violation otherwise)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE staging AS
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY ticker, concept, period_end, filed_date
                    ORDER BY value DESC
                ) AS rn
                FROM df_in
            ) WHERE rn = 1
        """)
        con.execute("""
            INSERT OR REPLACE INTO fundamentals
            (ticker, concept, period_end, fp, fy, filed_date, value, unit)
            SELECT ticker, concept, period_end, fp, fy, filed_date, value, unit
            FROM staging
        """)
        if verbose:
            n = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
            print(f"[SEC] fundamentals table now has {n:,} rows")
    finally:
        con.close()
    return counts
