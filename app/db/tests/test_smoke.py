"""Smoke tests for Supabase schema.

Run:  python -m pytest app/db/tests/test_smoke.py -v
Or:   python -m app.db.tests.test_smoke   (runs all checks, no pytest required)
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402


EXPECTED_TABLES = {
    "users", "tickers", "watchlist", "trade_log", "scan_results",
    "disclosures", "financials_eval", "factors_eval",
    "alerts", "alert_preferences", "macro_state", "bars",
    "health_ping", "_migrations",
}


def test_all_tables_exist():
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
            actual = {r[0] for r in cur.fetchall()}
    missing = EXPECTED_TABLES - actual
    assert not missing, f"missing tables: {missing}"


def test_rls_enabled_on_all_tables():
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND rowsecurity = false"
            )
            no_rls = [r[0] for r in cur.fetchall()]
    assert not no_rls, f"tables without RLS: {no_rls}"


def test_extensions_enabled():
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension")
            ext = {r[0] for r in cur.fetchall()}
    for needed in ("pg_trgm", "pgcrypto"):
        assert needed in ext, f"extension {needed} missing"


def test_tickers_crud():
    """End-to-end: insert/update/delete on tickers using service_role (RLS bypass)."""
    test_ticker = "_TEST.SMOKE"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tickers WHERE ticker = %s", (test_ticker,))
            cur.execute(
                "INSERT INTO tickers (ticker, name, market) VALUES (%s, %s, %s)",
                (test_ticker, "Smoke Test Corp", "KOSPI"),
            )
            cur.execute("SELECT name FROM tickers WHERE ticker = %s", (test_ticker,))
            row = cur.fetchone()
            assert row and row[0] == "Smoke Test Corp"
            cur.execute("DELETE FROM tickers WHERE ticker = %s", (test_ticker,))


def test_current_user_id_function_exists():
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user_id()")
            # service_role with no claim should return NULL
            val = cur.fetchone()[0]
    assert val is None  # acceptable; means bypass


def _main():
    checks = [
        ("all_tables_exist", test_all_tables_exist),
        ("rls_enabled", test_rls_enabled_on_all_tables),
        ("extensions", test_extensions_enabled),
        ("tickers_crud", test_tickers_crud),
        ("current_user_id_function", test_current_user_id_function_exists),
    ]
    failed = 0
    for name, fn in checks:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR   {name}: {type(e).__name__}: {e}")
            failed += 1
    print()
    if failed:
        print(f"{failed} smoke test(s) failed")
        sys.exit(1)
    print("All smoke tests passed")


if __name__ == "__main__":
    _main()
