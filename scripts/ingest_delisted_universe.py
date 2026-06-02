"""Ingest KR delisted universe to fix survivorship bias in backtest.

Source: FinanceDataReader's `KRX-DELISTING` listing.
Filters: 2010+ delisted, KOSPI/KOSDAQ, 6-char common stock codes
         (excludes preferred-stock ISIN-like 8-char symbols).
Target:
  - DuckDB data/backtest.duckdb bars (W + M, resampled from daily FDR)
  - Supabase tickers (delisted_at + is_active=false + listed_at + market + name)

Run once. Idempotent — safe to re-run on partial data.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from app.backtest import local_store
from app.db import get_conn
from app.db.ingest_bars import _resample_daily_to_rows

log = logging.getLogger("ingest_delisted")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def fetch_delisted_listing() -> pd.DataFrame:
    """Return KR delisted-since-2010 6-char common stocks."""
    import FinanceDataReader as fdr
    dl = fdr.StockListing("KRX-DELISTING")
    dl["DelistingDate"] = pd.to_datetime(dl["DelistingDate"], errors="coerce")
    dl["ListingDate"] = pd.to_datetime(dl["ListingDate"], errors="coerce")
    mask = (
        (dl["DelistingDate"] >= "2010-01-01")
        & (dl["DelistingDate"] <= "2026-05-31")
        & dl["Market"].isin(["KOSPI", "KOSDAQ"])
        & dl["Symbol"].astype(str).str.match(r"^\d{6}$")
    )
    out = dl.loc[mask, [
        "Symbol", "Name", "Market", "ListingDate", "DelistingDate", "Industry",
    ]].reset_index(drop=True)
    log.info("delisted universe: %d KOSPI/KOSDAQ 6-char tickers", len(out))
    return out


def to_ticker(symbol: str, market: str) -> str:
    suffix = "KS" if market == "KOSPI" else "KQ"
    return f"{symbol}.{suffix}"


def fetch_one_daily(symbol: str, delist: date) -> pd.DataFrame:
    import FinanceDataReader as fdr
    df = fdr.DataReader(symbol, "2000-01-01", delist.isoformat())
    if df is None or df.empty:
        return df
    # FDR returns 'Open/High/Low/Close/Volume' — resample expects lowercase.
    df = df.rename(columns={c: c.lower() for c in df.columns})
    # Drop terminal rows where OHLC went to 0 (post-trading-halt placeholders).
    df = df[df["close"] > 0]
    return df


def upsert_supabase_ticker(
    cur, ticker: str, name: str, market: str,
    listed_at, delisted_at, industry,
) -> None:
    cur.execute(
        """
        INSERT INTO tickers
            (ticker, name, market, industry, listed_at, delisted_at,
             is_active, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, false, NOW())
        ON CONFLICT (ticker) DO UPDATE SET
            name        = COALESCE(EXCLUDED.name, tickers.name),
            market      = EXCLUDED.market,
            industry    = COALESCE(EXCLUDED.industry, tickers.industry),
            listed_at   = COALESCE(EXCLUDED.listed_at, tickers.listed_at),
            delisted_at = COALESCE(EXCLUDED.delisted_at, tickers.delisted_at),
            is_active   = false,
            updated_at  = NOW()
        """,
        (ticker, name, market, industry,
         listed_at.date() if pd.notna(listed_at) else None,
         delisted_at.date() if pd.notna(delisted_at) else None),
    )


def main() -> int:
    listing = fetch_delisted_listing()
    if listing.empty:
        log.warning("No delisted tickers to ingest")
        return 0

    n_bars_total = 0
    n_skip_empty = 0
    n_err = 0
    n_supa = 0
    t0 = time.time()

    with local_store.connect() as duck_conn:
        with get_conn() as sup_conn:
            sup_cur = sup_conn.cursor()

            for i, row in listing.iterrows():
                sym = row["Symbol"]
                market = row["Market"]
                ticker = to_ticker(sym, market)
                delist = row["DelistingDate"].date()
                try:
                    daily = fetch_one_daily(sym, delist)
                    if daily is None or len(daily) == 0:
                        n_skip_empty += 1
                        continue
                    bar_rows = _resample_daily_to_rows(ticker, daily)
                    if not bar_rows:
                        n_skip_empty += 1
                        continue
                    df_bars = pd.DataFrame(bar_rows, columns=[
                        "ticker", "granularity", "bar_date",
                        "open", "high", "low", "close", "adj_close", "volume",
                    ])
                    local_store.upsert_bars(duck_conn, ticker, df_bars)
                    n_bars_total += len(bar_rows)

                    upsert_supabase_ticker(
                        sup_cur, ticker, row["Name"], market,
                        row["ListingDate"], row["DelistingDate"],
                        row.get("Industry"),
                    )
                    n_supa += 1

                    if (i + 1) % 50 == 0:
                        sup_conn.commit()
                        elapsed = time.time() - t0
                        log.info(
                            "[%d/%d] %s ok — %d bars total, %.1fs elapsed",
                            i + 1, len(listing), ticker, n_bars_total, elapsed,
                        )
                except Exception as e:
                    n_err += 1
                    if n_err <= 10:
                        log.warning("fail %s: %s", ticker, e)

            sup_conn.commit()

    elapsed = time.time() - t0
    log.info(
        "DONE — %d tickers ingested (%d bars), skipped_empty=%d errors=%d in %.1fs",
        n_supa, n_bars_total, n_skip_empty, n_err, elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
