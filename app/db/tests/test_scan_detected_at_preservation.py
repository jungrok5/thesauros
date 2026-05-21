"""Regression: scan_daily._flush_chunk preserves detected_at across runs.

Bug 2026-05-21 reported by jungrok5: telegram alerts (006400.KS,
003030.KS, 100090.KS, MSFT, NVDA) re-fire every time scan_daily runs
because each run re-stamps `scan_results.detected_at` with a new value
even when the underlying signal is unchanged. Same signal → new
detected_at → telegram_worker sees a "new" signal → another alert.

Fix (scan_daily.py:_flush_chunk):
  1. Before deactivating old rows, fetch their (ticker, signal_type,
     timeframe) → detected_at map.
  2. When inserting the new row, if that same key was previously
     active, REUSE the preserved detected_at instead of stamping a
     fresh `as_of`. Only a never-before-seen signal gets a fresh
     timestamp.

This locks the invariant: scan_results.detected_at == "first time we
saw this signal active, continuously." If the signal turns off and
later comes back on, you DO get a new detection time (the gap meant
it was a new event).

DB-backed (`@e2e.test` cleanup at teardown).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402


def _has_db() -> bool:
    return bool(os.environ.get("SUPABASE_DB_PASSWORD"))


@pytest.fixture
def test_ticker():
    """Create a transient TEST ticker; clean up afterwards."""
    if not _has_db():
        pytest.skip("DB not configured")
    suffix = uuid.uuid4().hex[:6].upper()
    ticker = f"DETPRSV{suffix}.TST"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tickers (ticker, name, market, is_active) "
                "VALUES (%s, %s, 'TEST', true) "
                "ON CONFLICT (ticker) DO NOTHING",
                (ticker, f"detected-at preservation {suffix}"),
            )
    yield ticker
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM scan_results WHERE ticker = %s", (ticker,))
            cur.execute("DELETE FROM analyze_results WHERE ticker = %s", (ticker,))
            cur.execute("DELETE FROM tickers WHERE ticker = %s", (ticker,))


def _flush(ticker: str, as_of: date, signal_type: str = "action_buy"):
    """Invoke the real _flush_chunk path with a single signal."""
    from app.db.scan_daily import _flush_chunk
    chunk = [{
        "ticker": ticker,
        "as_of": as_of,
        "signals": [{
            "signal_type": signal_type,
            "timeframe": "weekly",
            "strength": 0.7,
            "reason": "regression-test",
            "params": {},
        }],
    }]
    return _flush_chunk(chunk)


def test_same_signal_preserves_detected_at(test_ticker):
    """First run stamps detected_at; second run with same signal MUST
    NOT change it. Equivalent of 'cron runs twice in same week — alert
    should not re-fire'."""
    ticker = test_ticker
    today = date.today()

    # Run 1: signal first detected today.
    _flush(ticker, as_of=today)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT detected_at FROM scan_results "
                "WHERE ticker = %s AND signal_type = 'action_buy' "
                "AND is_active = true",
                (ticker,),
            )
            first = cur.fetchone()
    assert first is not None, "first run did not write scan_results row"
    first_detected_at = first[0]

    # Run 2 (later same week): same signal, BUT we pass a future
    # as_of to simulate the next-Friday cap. With the fix, the row's
    # detected_at must stay at the FIRST value.
    later_as_of = today + timedelta(days=3)
    _flush(ticker, as_of=later_as_of)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT detected_at FROM scan_results "
                "WHERE ticker = %s AND signal_type = 'action_buy' "
                "AND is_active = true",
                (ticker,),
            )
            second = cur.fetchone()
    assert second is not None, "second run did not write scan_results row"
    second_detected_at = second[0]

    assert second_detected_at == first_detected_at, (
        f"detected_at MUST be preserved across re-scans of the same active "
        f"signal — got first={first_detected_at} second={second_detected_at}. "
        f"This is the 2026-05-21 bug class: re-stamping causes telegram_worker "
        f"to treat unchanged signals as new alerts."
    )


def test_signal_off_then_on_gets_new_detected_at(test_ticker):
    """When the signal disappears (no row in next scan) and later
    reappears, we WANT a new detected_at (it's a new event). Lock this
    direction too — preservation is only across CONTINUOUSLY active."""
    ticker = test_ticker

    # Run 1: stamp signal.
    _flush(ticker, as_of=date.today() - timedelta(days=14))
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT detected_at FROM scan_results "
                "WHERE ticker = %s AND signal_type = 'action_buy' "
                "AND is_active = true",
                (ticker,),
            )
            t1 = cur.fetchone()[0]

    # Run 2: no signals for this ticker — deactivates the row.
    from app.db.scan_daily import _flush_chunk
    _flush_chunk([{
        "ticker": ticker,
        "as_of": date.today(),
        "signals": [],
    }])
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM scan_results "
                "WHERE ticker = %s AND is_active = true",
                (ticker,),
            )
            assert cur.fetchone()[0] == 0

    # Run 3: signal reappears — should get a FRESH detected_at.
    _flush(ticker, as_of=date.today())
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT detected_at FROM scan_results "
                "WHERE ticker = %s AND signal_type = 'action_buy' "
                "AND is_active = true",
                (ticker,),
            )
            t3 = cur.fetchone()[0]

    assert t3 != t1, (
        f"signal that went off and came back should get a new detected_at — "
        f"both were {t1}"
    )
