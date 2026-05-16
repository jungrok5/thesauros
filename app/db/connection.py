"""Supabase Postgres connection (psycopg + pool + supabase-py).

Two access paths:
  - `get_conn()`            : pooled psycopg.Connection (for DDL, batch
                              inserts, RLS-bypass via service_role)
  - `get_supabase_client()` : supabase-py Client (PostgREST API, respects RLS)

Both use credentials from .env. The DB password is required only for psycopg
(direct Postgres). PostgREST uses the service_role JWT.

Performance: long-running batches (scan_daily, ingest_news,
telegram_worker, eval_financials) churn through thousands of connections
without a pool — each TLS handshake costs 150-300ms. The module-level
ConnectionPool eliminates that cost.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Lock
from typing import Iterator, Optional
from urllib.parse import quote

import psycopg
from psycopg_pool import ConnectionPool


# Supabase free-tier projects use a regional connection pooler — direct
# `db.<ref>.supabase.co` is not reachable on IPv4. The pooler hostname is
# `aws-1-<region>.pooler.supabase.com` (the cluster prefix moved from
# `aws-0-` to `aws-1-` in 2025).
DEFAULT_POOLER_HOST_TPL = "aws-1-{region}.pooler.supabase.com"
DEFAULT_REGION = "ap-northeast-2"
TRANSACTION_PORT = 6543
SESSION_PORT = 5432

# Pool sizing — Supabase free-tier pooler caps at 60 conns total.
POOL_MIN = int(os.environ.get("SUPABASE_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("SUPABASE_POOL_MAX", "8"))


def get_dsn(*, mode: str = "transaction") -> str:
    """Build a Postgres DSN for the Supabase pooler.

    mode: "transaction" (port 6543, pgbouncer) or "session" (port 5432).
    Use session for queries that need prepared statements (e.g. cursors,
    SET commands). Transaction pooler is fine for most DDL/DML batches.

    Password is URL-encoded so passwords containing reserved chars
    (@, :, /, ?, #) don't break URI parsing.
    """
    url = os.environ["SUPABASE_URL"]
    pw = os.environ["SUPABASE_DB_PASSWORD"]
    ref = url.replace("https://", "").replace(".supabase.co", "")
    region = os.environ.get("SUPABASE_REGION", DEFAULT_REGION)
    host = os.environ.get("SUPABASE_POOLER_HOST",
                          DEFAULT_POOLER_HOST_TPL.format(region=region))
    port = SESSION_PORT if mode == "session" else TRANSACTION_PORT
    pw_safe = quote(pw, safe="")
    return f"postgresql://postgres.{ref}:{pw_safe}@{host}:{port}/postgres"


_pool: Optional[ConnectionPool] = None
_pool_lock = Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=get_dsn(mode="transaction"),
                    min_size=POOL_MIN, max_size=POOL_MAX,
                    open=True,
                    # PgBouncer (transaction pooler) doesn't support prepared
                    # statements — without this, psycopg3 errors with
                    # DuplicatePreparedStatement on the second SQL on any conn.
                    kwargs={"prepare_threshold": None},
                )
    return _pool


@contextmanager
def get_conn(*, mode: str = "transaction",
             autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a pooled psycopg.Connection. Always use as
    `with get_conn() as conn:` — the connection returns to the pool on exit.

    `mode='session'` falls back to a one-off non-pooled connection because
    the pool is configured against the transaction pooler URL. Session-mode
    callers are rare (DDL inside long-running transactions).
    """
    if mode == "session":
        conn = psycopg.connect(get_dsn(mode="session"),
                               autocommit=autocommit,
                               prepare_threshold=None)
        try:
            yield conn
            if not autocommit:
                conn.commit()
        except Exception:
            if not autocommit:
                conn.rollback()
            raise
        finally:
            conn.close()
        return

    pool = _get_pool()
    with pool.connection() as conn:
        # ConnectionPool.connection() yields with autocommit=False by default.
        if autocommit and not conn.autocommit:
            conn.autocommit = True
        try:
            yield conn
            if not autocommit:
                conn.commit()
        except Exception:
            if not autocommit:
                conn.rollback()
            raise
        finally:
            # Reset autocommit so the pool's expectations stay consistent.
            if autocommit:
                conn.autocommit = False


_supabase_client: Optional[object] = None


def get_supabase_client():
    """Singleton supabase-py client (service_role)."""
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _supabase_client
