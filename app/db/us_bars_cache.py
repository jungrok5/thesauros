"""us_bars / us_ticker_cache CRUD (Phase 6).

Read/write helpers + 7-day eviction logic. Uses service-role
psycopg connection (RLS bypass for writes).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pandas as pd

from app.db import get_conn


EVICTION_DAYS = 7


def load_bars(
    ticker: str, granularity: str = "W"
) -> Optional[pd.DataFrame]:
    """Load cached US bars as a DataFrame. Returns None if no cache."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_date, open, high, low, close, adj_close, volume "
                "FROM us_bars "
                "WHERE ticker = %s AND granularity = %s "
                "ORDER BY bar_date ASC",
                (ticker.upper(), granularity),
            )
            rows = cur.fetchall()
    if not rows:
        return None
    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def cache_age_days(ticker: str) -> Optional[int]:
    """Days since this ticker was last fetched. None if never cached."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_fetched_at FROM us_ticker_cache WHERE ticker = %s",
                (ticker.upper(),),
            )
            row = cur.fetchone()
    if not row:
        return None
    fetched_at = row[0]
    if isinstance(fetched_at, str):
        fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - fetched_at).days


def upsert_bars(
    ticker: str,
    granularity: str,
    rows: Sequence[Dict],
) -> int:
    """Upsert a batch of bars for one (ticker, granularity)."""
    if not rows:
        return 0
    ticker_u = ticker.upper()
    values = []
    for r in rows:
        values.append((
            ticker_u, granularity, r["date"],
            r.get("open"), r.get("high"), r.get("low"),
            r.get("close"), r.get("adj_close"), r.get("volume"),
        ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO us_bars "
                "(ticker, granularity, bar_date, open, high, low, "
                " close, adj_close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (ticker, granularity, bar_date) DO UPDATE SET "
                "  open = EXCLUDED.open, high = EXCLUDED.high, "
                "  low = EXCLUDED.low, close = EXCLUDED.close, "
                "  adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume",
                values,
            )
        conn.commit()
    return len(values)


def upsert_ticker_meta(
    ticker: str,
    name_en: Optional[str] = None,
    exchange: Optional[str] = None,
    sector: Optional[str] = None,
    last_bar_date: Optional[date] = None,
    bars_count: int = 0,
) -> None:
    """Upsert per-ticker metadata + refresh last_fetched_at."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO us_ticker_cache "
                "(ticker, name_en, exchange, sector, last_bar_date, "
                " bars_count, last_fetched_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT (ticker) DO UPDATE SET "
                "  name_en = COALESCE(EXCLUDED.name_en, us_ticker_cache.name_en), "
                "  exchange = COALESCE(EXCLUDED.exchange, us_ticker_cache.exchange), "
                "  sector = COALESCE(EXCLUDED.sector, us_ticker_cache.sector), "
                "  last_bar_date = COALESCE(EXCLUDED.last_bar_date, us_ticker_cache.last_bar_date), "
                "  bars_count = EXCLUDED.bars_count, "
                "  last_fetched_at = NOW()",
                (ticker.upper(), name_en, exchange, sector,
                 last_bar_date, bars_count),
            )
        conn.commit()


def evict_stale(older_than_days: int = EVICTION_DAYS) -> int:
    """Delete tickers whose last_fetched_at is older than the cutoff.
    Also deletes their bars (no FK cascade — handled in transaction).
    Returns count of tickers evicted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM us_ticker_cache "
                "WHERE last_fetched_at < %s",
                (cutoff,),
            )
            stale = [r[0] for r in cur.fetchall()]
            if not stale:
                return 0
            cur.executemany(
                "DELETE FROM us_bars WHERE ticker = %s",
                [(t,) for t in stale],
            )
            cur.executemany(
                "DELETE FROM us_ticker_cache WHERE ticker = %s",
                [(t,) for t in stale],
            )
        conn.commit()
    return len(stale)


def list_cached_tickers() -> List[Dict]:
    """List all currently-cached tickers with metadata."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, name_en, exchange, sector, "
                "  last_bar_date, bars_count, last_fetched_at "
                "FROM us_ticker_cache "
                "ORDER BY last_fetched_at DESC"
            )
            rows = cur.fetchall()
    return [
        {
            "ticker": r[0], "name_en": r[1], "exchange": r[2],
            "sector": r[3], "last_bar_date": r[4],
            "bars_count": r[5], "last_fetched_at": r[6],
        }
        for r in rows
    ]
