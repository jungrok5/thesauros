"""Local DuckDB store for backtest bars (2008-now, KOSPI + KOSDAQ).

Why local: Supabase `bars` retains only ~2 years (240MA + scan window).
Backtest needs 17+ years of weekly + monthly bars to cover the book's
case studies (2008 - present) plus deeper out-of-sample windows.

Why DuckDB:
  - Columnar storage → 10-100x faster than SQLite for analytical
    aggregations (per-ticker walks).
  - Single-file (data/backtest.duckdb), gitignored.
  - Native pandas integration (no row-by-row INSERT — direct
    register-and-INSERT-FROM-SELECT).
  - Concurrent reads safe; writes serialized via single connection.

Schema:
    bars(ticker, granularity, bar_date, open, high, low, close, adj_close, volume)
        PRIMARY KEY (ticker, granularity, bar_date)
    ingest_log(ticker, last_fetched_ts, source, n_bars, n_errors)
        tracks per-ticker fetch state for resumable backfill

Lifecycle:
  1. scripts/build_local_bars.py → initial 2008-now backfill (parallel FDR)
  2. Daily/weekly cron append (TODO: incremental update)
  3. backtest modules read via load_bars_local(ticker, granularity)

Public API:
    connect() → duckdb.DuckDBPyConnection (context-managed)
    ensure_schema(conn)
    upsert_bars(conn, ticker, bars_df)
    load_bars(ticker, granularity='W', start=None, end=None) → pd.DataFrame
    list_ingested_tickers(conn) → set[str]
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, List, Optional, Set

import duckdb
import pandas as pd

log = logging.getLogger("backtest.local_store")

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _ROOT / "data" / "backtest.duckdb"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bars (
    ticker       VARCHAR NOT NULL,
    granularity  VARCHAR NOT NULL,   -- 'D' / 'W' / 'M'
    bar_date     DATE    NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    adj_close    REAL,
    volume       BIGINT,
    PRIMARY KEY (ticker, granularity, bar_date)
);

CREATE INDEX IF NOT EXISTS idx_bars_date ON bars(bar_date);

CREATE TABLE IF NOT EXISTS ingest_log (
    ticker            VARCHAR PRIMARY KEY,
    last_fetched_ts   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source            VARCHAR,        -- 'fdr' / 'naver' / etc.
    range_start       DATE,
    range_end         DATE,
    n_bars            INTEGER,
    n_errors          INTEGER DEFAULT 0,
    notes             VARCHAR
);
"""


@contextlib.contextmanager
def connect(
    db_path: Optional[Path] = None, read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the local DuckDB. Creates parent dir + schema if missing."""
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path), read_only=read_only)
    try:
        if not read_only:
            ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_SCHEMA_SQL)


def upsert_bars(
    conn: duckdb.DuckDBPyConnection, ticker: str, bars_df: pd.DataFrame,
) -> int:
    """Insert/update rows for one ticker from a DataFrame.

    Expected columns: granularity, bar_date (or date), open, high, low,
    close, adj_close, volume. Extra columns ignored. Returns rows written.

    Uses INSERT OR REPLACE (DuckDB) — duplicates by (ticker, granularity,
    bar_date) get overwritten. Safe to re-run on partial data.
    """
    if bars_df is None or bars_df.empty:
        return 0
    df = bars_df.copy()
    # Normalize column names — single source of truth: bar_date.
    if "bar_date" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "bar_date"})
    df["ticker"] = ticker
    # Ensure types.
    df["bar_date"] = pd.to_datetime(df["bar_date"]).dt.date
    for c in ("open", "high", "low", "close", "adj_close"):
        if c not in df.columns:
            df[c] = None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    if "granularity" not in df.columns:
        raise ValueError("bars_df must include 'granularity' column")
    cols = ["ticker", "granularity", "bar_date", "open", "high", "low",
            "close", "adj_close", "volume"]
    df = df[cols]
    # Register the DataFrame as a temp table and INSERT OR REPLACE.
    conn.register("_tmp_bars", df)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO bars "
            "SELECT * FROM _tmp_bars"
        )
    finally:
        conn.unregister("_tmp_bars")
    return len(df)


def record_ingest(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    source: str = "fdr",
    range_start: Optional[date] = None,
    range_end: Optional[date] = None,
    n_bars: int = 0,
    n_errors: int = 0,
    notes: str = "",
) -> None:
    """Record that ticker was fetched (idempotent — overwrites prior log)."""
    conn.execute(
        """
        INSERT OR REPLACE INTO ingest_log
            (ticker, last_fetched_ts, source, range_start, range_end,
             n_bars, n_errors, notes)
        VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """,
        [ticker, source, range_start, range_end, n_bars, n_errors, notes],
    )


def list_ingested_tickers(conn: duckdb.DuckDBPyConnection) -> Set[str]:
    """Tickers that have already been backfilled (any bars in store)."""
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM bars"
    ).fetchall()
    return {r[0] for r in rows}


def load_bars(
    ticker: str,
    granularity: str = "W",
    start: Optional[date] = None,
    end: Optional[date] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Load bars for a ticker from the local store.

    Convenience read-only path used by the backtest modules. Returns a
    DataFrame with columns date / open / high / low / close / adj_close
    / volume (mirroring the Supabase `load_weekly_bars` shape) so the
    backtest can swap between sources transparently.

    Returns empty DataFrame if ticker absent (no exception).
    """
    path = db_path or DEFAULT_DB_PATH
    if not path.exists():
        return pd.DataFrame()
    where = ["ticker = ?", "granularity = ?"]
    params: list = [ticker, granularity]
    if start is not None:
        where.append("bar_date >= ?")
        params.append(start)
    if end is not None:
        where.append("bar_date <= ?")
        params.append(end)
    sql = (
        "SELECT bar_date AS date, open, high, low, close, adj_close, volume "
        "FROM bars WHERE " + " AND ".join(where) +
        " ORDER BY bar_date"
    )
    with connect(path, read_only=True) as conn:
        df = conn.execute(sql, params).df()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df.attrs["grain"] = granularity
    return df


@dataclass
class StoreStats:
    n_tickers: int
    n_bars_total: int
    n_bars_W: int
    n_bars_M: int
    n_bars_D: int
    earliest: Optional[date]
    latest: Optional[date]
    db_size_mb: float


def store_stats(db_path: Optional[Path] = None) -> StoreStats:
    """Diagnostics: how big, how many tickers, date range."""
    path = db_path or DEFAULT_DB_PATH
    if not path.exists():
        return StoreStats(0, 0, 0, 0, 0, None, None, 0.0)
    with connect(path, read_only=True) as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT ticker), COUNT(*) FROM bars"
        ).fetchone()
        n_tickers, n_total = row[0], row[1]
        gran_counts = dict(
            conn.execute(
                "SELECT granularity, COUNT(*) FROM bars GROUP BY granularity"
            ).fetchall()
        )
        date_row = conn.execute(
            "SELECT MIN(bar_date), MAX(bar_date) FROM bars"
        ).fetchone()
    return StoreStats(
        n_tickers=n_tickers,
        n_bars_total=n_total,
        n_bars_W=gran_counts.get("W", 0),
        n_bars_M=gran_counts.get("M", 0),
        n_bars_D=gran_counts.get("D", 0),
        earliest=date_row[0],
        latest=date_row[1],
        db_size_mb=path.stat().st_size / (1024 * 1024),
    )
