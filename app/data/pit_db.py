"""DuckDB connection + schema for the PIT (point-in-time) database.

Tables:
  universe(ticker, cik, name, sector, gics_industry, added_date)
  prices(ticker, date, open, high, low, close, adj_close, volume)
  fundamentals(ticker, concept, period_end, fp, fy, filed_date, value, unit)
      ├─ "fp" = fiscal period (Q1/Q2/Q3/FY)
      ├─ "fy" = fiscal year
      └─ "filed_date" is the actual SEC submission date — this is the PIT key.
  meta(key, value, ts)

All "as-of t" queries filter by filed_date <= t (or trade_date <= t for prices).
"""
from __future__ import annotations

import contextlib
from typing import Iterator

import duckdb

from app.config import DUCKDB_PATH


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS universe (
    ticker        VARCHAR PRIMARY KEY,
    cik           VARCHAR,
    name          VARCHAR,
    sector        VARCHAR,
    gics_industry VARCHAR,
    added_date    DATE,
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS prices (
    ticker     VARCHAR,
    date       DATE,
    open       DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    close      DOUBLE,
    adj_close  DOUBLE,
    volume     BIGINT,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker      VARCHAR,
    concept     VARCHAR,
    period_end  DATE,
    fp          VARCHAR,
    fy          INTEGER,
    filed_date  DATE,
    value       DOUBLE,
    unit        VARCHAR,
    PRIMARY KEY (ticker, concept, period_end, filed_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_filed ON fundamentals(ticker, filed_date);

CREATE TABLE IF NOT EXISTS meta (
    key  VARCHAR PRIMARY KEY,
    value VARCHAR,
    ts   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS macro (
    series_id VARCHAR,
    date      DATE,
    value     DOUBLE,
    PRIMARY KEY (series_id, date)
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro(date);
"""


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(DUCKDB_PATH)
    con.execute(SCHEMA_SQL)
    return con


@contextlib.contextmanager
def cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect()
    try:
        yield con
    finally:
        con.close()


def get_meta(key: str) -> str | None:
    with cursor() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", [key]).fetchone()
        return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    with cursor() as con:
        con.execute("DELETE FROM meta WHERE key=?", [key])
        con.execute("INSERT INTO meta(key,value) VALUES(?,?)", [key, value])


def stats() -> dict:
    with cursor() as con:
        return {
            "universe": con.execute("SELECT COUNT(*) FROM universe").fetchone()[0],
            "prices_rows": con.execute("SELECT COUNT(*) FROM prices").fetchone()[0],
            "prices_tickers": con.execute(
                "SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0],
            "prices_min": con.execute("SELECT MIN(date) FROM prices").fetchone()[0],
            "prices_max": con.execute("SELECT MAX(date) FROM prices").fetchone()[0],
            "fundamentals_rows": con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0],
            "fundamentals_tickers": con.execute(
                "SELECT COUNT(DISTINCT ticker) FROM fundamentals").fetchone()[0],
        }
