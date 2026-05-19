"""DB-backed test: the AFTER INSERT trigger on `search_history` trims
each user's history to the 30 newest rows.

This is the only retention mechanism for the table — there's no entry in
`app.db.retention.POLICIES` for it. If the trigger silently breaks (e.g.
a future migration drops it without re-creating), this test fails on the
next CI run, before users start eating into the 500 MB budget.

The test uses a real Supabase connection (matching other tests in this
module), creates a transient @e2e.test user, inserts 31 history rows,
asserts only 30 survive, and cleans up.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402


@pytest.fixture
def transient_user():
    """Create a throwaway @e2e.test user; tear down on test exit.

    The user-row tear-down also cascades search_history rows via
    ON DELETE CASCADE on the FK, so no manual history cleanup needed.
    """
    email = f"trigger-test-{uuid.uuid4().hex[:8]}@e2e.test"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, access_status) "
                "VALUES (%s, 'approved') RETURNING id",
                (email,),
            )
            user_id = cur.fetchone()[0]
    yield user_id
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


def _history_count(user_id: str) -> int:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM search_history WHERE user_id = %s",
                (user_id,),
            )
            return cur.fetchone()[0]


def test_trigger_trims_to_30_newest(transient_user):
    """Insert 31 rows and assert the trigger leaves exactly 30."""
    user_id = transient_user

    # Insert 31 rows; trigger fires AFTER each one, so the 31st insert
    # is the one that deletes the oldest row.
    with get_conn() as conn:
        with conn.cursor() as cur:
            for i in range(31):
                cur.execute(
                    "INSERT INTO search_history (user_id, query, ticker) "
                    "VALUES (%s, %s, %s)",
                    (user_id, f"query{i}", f"TICK{i}"),
                )

    assert _history_count(user_id) == 30


def test_trigger_keeps_only_newest_30(transient_user):
    """The 30 surviving rows must be the 30 most recently inserted —
    i.e., queries 1..30 (zero-indexed), not 0..29."""
    user_id = transient_user

    with get_conn() as conn:
        with conn.cursor() as cur:
            for i in range(31):
                cur.execute(
                    "INSERT INTO search_history (user_id, query) "
                    "VALUES (%s, %s)",
                    (user_id, f"query{i:02d}"),
                )

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query FROM search_history "
                "WHERE user_id = %s ORDER BY created_at ASC",
                (user_id,),
            )
            queries = [r[0] for r in cur.fetchall()]

    # The oldest (query00) was trimmed; query01..query30 remain.
    assert queries[0] == "query01"
    assert queries[-1] == "query30"
    assert len(queries) == 30


def test_trigger_scoped_per_user(transient_user):
    """Inserting many rows for user A must not delete user B's rows."""
    user_a = transient_user
    # Make another user inline so both fixtures don't fight over the
    # same scope; clean up at the end.
    email_b = f"trigger-test-b-{uuid.uuid4().hex[:8]}@e2e.test"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, access_status) "
                "VALUES (%s, 'approved') RETURNING id",
                (email_b,),
            )
            user_b = cur.fetchone()[0]

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 5 rows for B.
                for i in range(5):
                    cur.execute(
                        "INSERT INTO search_history (user_id, query) "
                        "VALUES (%s, %s)",
                        (user_b, f"b{i}"),
                    )
                # 40 for A — well over the cap.
                for i in range(40):
                    cur.execute(
                        "INSERT INTO search_history (user_id, query) "
                        "VALUES (%s, %s)",
                        (user_a, f"a{i}"),
                    )

        assert _history_count(user_a) == 30
        assert _history_count(user_b) == 5  # untouched
    finally:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_b,))
