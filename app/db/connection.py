"""Supabase Postgres connection (psycopg + supabase-py).

Two access paths:
  - `get_conn()`            : raw psycopg.Connection (for DDL, batch inserts, RLS-bypass via service_role)
  - `get_supabase_client()` : supabase-py Client (PostgREST API, respects RLS by default)

Both use credentials from .env. The DB password is required only for psycopg
(direct Postgres). PostgREST uses the service_role JWT.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg


# Supabase free-tier projects use a regional connection pooler — direct
# `db.<ref>.supabase.co` is not reachable on IPv4. The pooler hostname is
# `aws-1-<region>.pooler.supabase.com` (the cluster prefix moved from
# `aws-0-` to `aws-1-` in 2025).
DEFAULT_POOLER_HOST_TPL = "aws-1-{region}.pooler.supabase.com"
DEFAULT_REGION = "ap-northeast-2"
TRANSACTION_PORT = 6543
SESSION_PORT = 5432


def get_dsn(*, mode: str = "transaction") -> str:
    """Build a Postgres DSN for the Supabase pooler.

    mode: "transaction" (port 6543, pgbouncer) or "session" (port 5432).
    Use session for queries that need prepared statements (e.g. cursors,
    SET commands). Transaction pooler is fine for most DDL/DML batches.
    """
    url = os.environ["SUPABASE_URL"]
    pw = os.environ["SUPABASE_DB_PASSWORD"]
    ref = url.replace("https://", "").replace(".supabase.co", "")
    region = os.environ.get("SUPABASE_REGION", DEFAULT_REGION)
    host = os.environ.get("SUPABASE_POOLER_HOST",
                          DEFAULT_POOLER_HOST_TPL.format(region=region))
    port = SESSION_PORT if mode == "session" else TRANSACTION_PORT
    return f"postgresql://postgres.{ref}:{pw}@{host}:{port}/postgres"


@contextmanager
def get_conn(*, mode: str = "transaction",
             autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a psycopg.Connection. Always use as `with get_conn() as conn:`.

    The transaction pooler (port 6543, PgBouncer) is incompatible with
    psycopg3's auto-prepared statements (DuplicatePreparedStatement). We
    pin `prepare_threshold=None` so every statement is sent as a simple
    Query. Session mode (5432) doesn't need this but the flag is harmless.
    """
    dsn = get_dsn(mode=mode)
    conn = psycopg.connect(dsn, autocommit=autocommit, prepare_threshold=None)
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
