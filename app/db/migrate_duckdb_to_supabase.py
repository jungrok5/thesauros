"""One-shot migration: DuckDB → Supabase.

What's copied:
  • bars_daily       : last `years_prices` (default 8) of daily OHLCV
  • fundamentals     : FY-only since `fund_min_year` (default 2020)
  • macro_series     : full FRED + yfinance series (small)

What's NOT copied (intentionally):
  • Delisted-only tickers       (post-pivot, we don't care)
  • Quarterly fundamentals      (eval_financials uses FY only)
  • insider_transactions, paper_trades, meta (legacy from backtest era)

Strategy:
  • Filter to tickers present in Supabase `tickers` master (FK safety).
  • Stream into Postgres via psycopg COPY (10-100x faster than INSERT).
  • Idempotent: ON CONFLICT DO NOTHING (re-run is safe; only adds new
    rows after the latest existing).

Usage:
    python -m app.db.migrate_duckdb_to_supabase --all
    python -m app.db.migrate_duckdb_to_supabase --prices-only --years 5
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

import duckdb
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("migrate")


def _allowed_tickers() -> set:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM tickers WHERE is_active = true")
            return {r[0] for r in cur.fetchall()}


def _copy_into(table: str, columns: List[str], rows_iter) -> int:
    """Use COPY for fast bulk insert. rows_iter yields tab-separated lines."""
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            with cur.copy(
                f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\\\N')"
            ) as copy:
                for line in rows_iter:
                    copy.write(line + "\n")
                    n += 1
    return n


def migrate_prices(con: duckdb.DuckDBPyConnection, years: int = 8,
                   chunk_size: int = 100_000) -> int:
    """Stream prices into bars_daily, skipping rows whose ticker isn't in
    our active master."""
    allowed = _allowed_tickers()
    log.info("prices: allowed tickers = %d", len(allowed))

    # Pull row IDs in chunks, filter, COPY
    n_total = 0
    offset = 0
    cutoff = f"{2026 - years}-01-01"
    log.info("prices: cutoff = %s", cutoff)

    while True:
        df = con.execute(
            "SELECT ticker, date, open, high, low, close, adj_close, volume "
            "FROM prices WHERE date >= ? ORDER BY ticker, date "
            "LIMIT ? OFFSET ?", [cutoff, chunk_size, offset]
        ).df()
        if df.empty:
            break
        df = df[df["ticker"].isin(allowed)]
        if df.empty:
            offset += chunk_size
            continue

        # Format as CSV-with-tab, NULL as \N
        buf = io.StringIO()
        for _, r in df.iterrows():
            buf.write("\t".join([
                str(r["ticker"]),
                str(r["date"]),
                f"{r['open']}"      if r['open'] is not None      else r"\N",
                f"{r['high']}"      if r['high'] is not None      else r"\N",
                f"{r['low']}"       if r['low'] is not None       else r"\N",
                f"{r['close']}"     if r['close'] is not None     else r"\N",
                f"{r['adj_close']}" if r['adj_close'] is not None else r"\N",
                str(int(r['volume']))  if r['volume'] is not None and r['volume'] == r['volume'] else r"\N",
            ]) + "\n")
        buf.seek(0)

        # Use COPY, but Supabase pooler doesn't support COPY cleanly with FK
        # We'll INSERT with ON CONFLICT instead — slower but works on pgbouncer.
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO bars_daily
                      (ticker, bar_date, open, high, low, close, adj_close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, bar_date) DO NOTHING
                    """,
                    [(
                        r["ticker"], r["date"],
                        float(r["open"]) if r["open"] is not None else None,
                        float(r["high"]) if r["high"] is not None else None,
                        float(r["low"]) if r["low"] is not None else None,
                        float(r["close"]) if r["close"] is not None else None,
                        float(r["adj_close"]) if r["adj_close"] is not None else None,
                        int(r["volume"]) if r["volume"] is not None and r["volume"] == r["volume"] else None,
                    ) for _, r in df.iterrows()],
                )
        n_total += len(df)
        log.info("  prices: chunk %d, +%d rows (running total: %d)",
                 offset // chunk_size, len(df), n_total)
        offset += chunk_size

    return n_total


def migrate_fundamentals(con: duckdb.DuckDBPyConnection,
                          min_year: int = 2020) -> int:
    allowed = _allowed_tickers()
    log.info("fundamentals: allowed tickers = %d", len(allowed))
    df = con.execute(
        "SELECT ticker, concept, fy, period_end, filed_date, value, unit "
        "FROM fundamentals WHERE fp = 'FY' AND fy >= ? AND value IS NOT NULL",
        [min_year]
    ).df()
    df = df[df["ticker"].isin(allowed)]
    log.info("fundamentals: %d FY rows after filter", len(df))
    if df.empty:
        return 0

    BATCH = 5000
    n = 0
    for i in range(0, len(df), BATCH):
        chunk = df.iloc[i:i + BATCH]
        rows = []
        for _, r in chunk.iterrows():
            try:
                fy = int(r["fy"])
            except (TypeError, ValueError):
                continue
            rows.append((
                r["ticker"], r["concept"], fy,
                r["period_end"], r["filed_date"],
                float(r["value"]) if r["value"] is not None else None,
                r.get("unit"),
            ))
        if not rows:
            continue
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO fundamentals
                      (ticker, concept, fy, period_end, filed_date, value, unit)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, concept, fy) DO UPDATE SET
                      value = EXCLUDED.value,
                      period_end = EXCLUDED.period_end,
                      filed_date = EXCLUDED.filed_date
                    """,
                    rows,
                )
        n += len(rows)
        log.info("  fundamentals: %d / %d", n, len(df))
    return n


def migrate_macro(con: duckdb.DuckDBPyConnection) -> int:
    df = con.execute(
        "SELECT series_id, date, value FROM macro WHERE value IS NOT NULL"
    ).df()
    if df.empty:
        return 0
    log.info("macro: %d rows", len(df))
    BATCH = 10000
    n = 0
    for i in range(0, len(df), BATCH):
        chunk = df.iloc[i:i + BATCH]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO macro_series (series_id, date, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (series_id, date) DO UPDATE SET
                      value = EXCLUDED.value
                    """,
                    [(r["series_id"], r["date"], float(r["value"]))
                     for _, r in chunk.iterrows()],
                )
        n += len(chunk)
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true")
    p.add_argument("--prices-only", action="store_true")
    p.add_argument("--fundamentals-only", action="store_true")
    p.add_argument("--macro-only", action="store_true")
    p.add_argument("--years", type=int, default=8)
    p.add_argument("--fund-min-year", type=int, default=2020)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if not (args.all or args.prices_only or args.fundamentals_only or args.macro_only):
        p.error("specify --all / --prices-only / --fundamentals-only / --macro-only")

    con = duckdb.connect("data/pit.duckdb", read_only=True)
    t0 = time.time()

    if args.all or args.macro_only:
        n = migrate_macro(con)
        log.info("MACRO done: %d rows (%.1fs)", n, time.time() - t0)
    if args.all or args.fundamentals_only:
        t = time.time()
        n = migrate_fundamentals(con, min_year=args.fund_min_year)
        log.info("FUNDAMENTALS done: %d rows (%.1fs)", n, time.time() - t)
    if args.all or args.prices_only:
        t = time.time()
        n = migrate_prices(con, years=args.years)
        log.info("PRICES done: %d rows (%.1fs)", n, time.time() - t)

    log.info("total %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
