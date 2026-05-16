"""Database layer — Supabase Postgres connection + migrations.

Public API:
  - get_conn()           : context manager yielding psycopg.Connection
  - get_supabase_client(): supabase-py Client (PostgREST + Auth)
  - apply_migrations()   : run migrations/*.sql in order
"""
from app.db.connection import get_conn, get_supabase_client, get_dsn

__all__ = ["get_conn", "get_supabase_client", "get_dsn"]
