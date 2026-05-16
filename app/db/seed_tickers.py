"""Seed tickers master into Supabase.

Sources:
  - FinanceDataReader.StockListing("KRX") → KOSPI/KOSDAQ
  - app.data.universe.fetch_sp500_table()  → S&P 500 (US)

Idempotent: ON CONFLICT DO UPDATE on `tickers.ticker`.

Usage:
    python -m app.db.seed_tickers --markets kospi kosdaq sp500
    python -m app.db.seed_tickers --markets kospi    # KOSPI only
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
        out.append((ticker, name, "NASDAQ", sector, industry))  # market name approximate
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


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+", default=["kospi", "kosdaq", "sp500"],
                   choices=["kospi", "kosdaq", "sp500"],
                   help="which markets to seed")
    args = p.parse_args(argv)

    total = 0
    if "kospi" in args.markets or "kosdaq" in args.markets:
        print("fetching KR universe (FDR)...")
        kr = fetch_kr_universe()
        if "kospi" not in args.markets:
            kr = [r for r in kr if r[2] != "KOSPI"]
        if "kosdaq" not in args.markets:
            kr = [r for r in kr if r[2] != "KOSDAQ"]
        print(f"  KR rows: {len(kr)}")
        upsert(kr)
        total += len(kr)

    if "sp500" in args.markets:
        print("fetching US S&P500 (Wikipedia)...")
        us = fetch_us_sp500()
        print(f"  US rows: {len(us)}")
        upsert(us)
        total += len(us)

    print(f"upserted {total} tickers total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
