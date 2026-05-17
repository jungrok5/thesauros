"""Seed (and refresh) the tickers master into Supabase.

Sources:
  - FinanceDataReader.StockListing("KRX") → KOSPI / KOSDAQ
  - Nasdaq Trader nasdaqlisted.txt + otherlisted.txt → US NASDAQ / NYSE / AMEX
  - app.data.universe.fetch_sp500_table()           → S&P 500 (fallback)

Idempotent: ON CONFLICT DO UPDATE on `tickers.ticker`.

Refresh semantics (--refresh):
  Anything in the master that is NO LONGER returned by the fresh fetch
  is marked is_active = false (delisted / removed from exchange listing).
  Newly listed tickers are inserted normally.

Usage:
    python -m app.db.seed_tickers --markets kospi kosdaq us   # everything
    python -m app.db.seed_tickers --markets us                # NASDAQ+NYSE+AMEX
    python -m app.db.seed_tickers --refresh                   # mark missing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402


def fetch_kr_universe() -> List[Tuple[str, str, str, str | None, str | None]]:
    """Returns list of (ticker, name, market, sector, industry)."""
    import FinanceDataReader as fdr
    listing = fdr.StockListing("KRX")
    out = []
    for _, row in listing.iterrows():
        code = str(row.get("Code", "")).strip()
        if not code.isdigit() or len(code) != 6:
            continue
        market_id = str(row.get("MarketId", "")).strip()
        market_name = str(row.get("Market", "")).strip().upper()
        if "STK" in market_id or market_name == "KOSPI":
            suffix, market = ".KS", "KOSPI"
        elif "KSQ" in market_id or market_name == "KOSDAQ":
            suffix, market = ".KQ", "KOSDAQ"
        else:
            continue
        ticker = f"{code}{suffix}"
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        sector = (row.get("Sector") or "") or None
        industry = (row.get("Industry") or "") or None
        out.append((ticker, name, market, sector, industry))
    return out


def fetch_us_sp500() -> List[Tuple[str, str, str, str | None, str | None]]:
    """Returns list of (ticker, name, market, sector, industry)."""
    from app.data.universe import fetch_sp500_table
    df = fetch_sp500_table()
    out = []
    for _, row in df.iterrows():
        ticker = str(row["ticker"]).strip()
        name = str(row["name"]).strip()
        sector = (str(row.get("sector")) or "").strip() or None
        industry = (str(row.get("sub_industry")) or "").strip() or None
        if not ticker or not name:
            continue
        out.append((ticker, name, "NASDAQ", sector, industry))
    return out


_NASDAQ_TRADER_URLS = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
_EXCHANGE_MAP = {"N": "NYSE", "A": "AMEX", "P": "ARCA", "Z": "BATS"}


def fetch_us_all() -> List[Tuple[str, str, str, str | None, str | None]]:
    """Returns all US-listed equities from Nasdaq Trader symbol files
    (the same files brokers use).

    nasdaqlisted.txt covers NASDAQ. otherlisted.txt covers NYSE/AMEX/ARCA.
    We drop ETFs, test issues, special-character tickers (warrants, units,
    preferred shares — e.g. `AAPL.WS`, `AAPL.U`, `AAPL.A` are filtered).
    """
    import requests
    out: List[Tuple[str, str, str, str | None, str | None]] = []

    # NASDAQ-listed
    r = requests.get(_NASDAQ_TRADER_URLS["nasdaqlisted"],
                     timeout=30, headers={"User-Agent": "Mozilla/5.0 (research)"})
    r.raise_for_status()
    for line in r.text.splitlines()[1:]:
        if not line or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        sym, name, mkt_cat, test, fin_status, _round, etf, _ns = parts[:8]
        if test == "Y" or etf == "Y":
            continue
        # Skip warrants/units/non-common share classes (dots, $, ^)
        if not sym.isalpha():
            continue
        if not name.strip():
            continue
        out.append((sym, name.strip(), "NASDAQ", None, None))

    # NYSE + AMEX + ARCA + BATS
    r = requests.get(_NASDAQ_TRADER_URLS["otherlisted"],
                     timeout=30, headers={"User-Agent": "Mozilla/5.0 (research)"})
    r.raise_for_status()
    for line in r.text.splitlines()[1:]:
        if not line or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        sym, name, exch, _cqs, etf, _round, test, _nasdaq = parts[:8]
        if test == "Y" or etf == "Y":
            continue
        if not sym.isalpha():
            continue
        if not name.strip():
            continue
        market = _EXCHANGE_MAP.get(exch, "OTHER")
        out.append((sym, name.strip(), market, None, None))

    return out


def upsert(rows: List[Tuple[str, str, str, str | None, str | None]]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO tickers (ticker, name, market, sector, industry)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    name = EXCLUDED.name,
                    market = EXCLUDED.market,
                    sector = COALESCE(EXCLUDED.sector, tickers.sector),
                    industry = COALESCE(EXCLUDED.industry, tickers.industry),
                    is_active = true,
                    updated_at = now()
                """,
                rows,
            )
    return len(rows)


def mark_missing_inactive(seen_tickers: List[str], markets: List[str]) -> int:
    """Mark previously-active tickers as is_active=false when they no
    longer appear in the freshly fetched universe.

    `markets` is the set of market codes (KOSPI/KOSDAQ/NASDAQ/NYSE/AMEX/...)
    that this refresh actually covered. We only touch rows in those
    markets so partial fetches don't deactivate everything else.
    """
    if not markets:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tickers
                SET is_active = false, updated_at = now()
                WHERE is_active = true
                  AND market = ANY(%s)
                  AND ticker <> ALL(%s)
                """,
                (list(markets), list(seen_tickers)),
            )
            return cur.rowcount


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+",
                   default=["kospi", "kosdaq", "us"],
                   choices=["kospi", "kosdaq", "sp500", "us"],
                   help="which markets to seed (us = full NASDAQ+NYSE+AMEX)")
    p.add_argument("--refresh", action="store_true",
                   help="mark missing tickers as is_active=false")
    args = p.parse_args(argv)

    total = 0
    all_rows: List[Tuple[str, str, str, str | None, str | None]] = []

    if "kospi" in args.markets or "kosdaq" in args.markets:
        print("fetching KR universe (FDR)...")
        kr = fetch_kr_universe()
        if "kospi" not in args.markets:
            kr = [r for r in kr if r[2] != "KOSPI"]
        if "kosdaq" not in args.markets:
            kr = [r for r in kr if r[2] != "KOSDAQ"]
        print(f"  KR rows: {len(kr)}")
        upsert(kr)
        all_rows += kr
        total += len(kr)

    if "us" in args.markets:
        print("fetching US universe (Nasdaq Trader)...")
        us = fetch_us_all()
        print(f"  US rows: {len(us)}")
        upsert(us)
        all_rows += us
        total += len(us)
    elif "sp500" in args.markets:
        print("fetching US S&P500 (Wikipedia)...")
        us = fetch_us_sp500()
        print(f"  US rows: {len(us)}")
        upsert(us)
        all_rows += us
        total += len(us)

    print(f"upserted {total} tickers total")

    if args.refresh:
        seen = [r[0] for r in all_rows]
        markets_covered = sorted({r[2] for r in all_rows})
        deactivated = mark_missing_inactive(seen, markets_covered)
        print(f"refresh: marked {deactivated} tickers is_active=false "
              f"(no longer in {markets_covered})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
