"""Telegram worker lease guard (replaces test_telegram_worker_lock.py).

Pins the 2026-05-28 v2 race-condition fix:

  Symptom (v1 / advisory lock): 4 enter-class alerts went out 2× each.
    Concurrent telegram_worker dispatches all read `alerts` before any
    insert landed, hit the same dedup miss, and double-sent.

  Symptom (v1 in production): Supavisor pooled sessions held the
    pg_try_advisory_lock past the client conn close. Lock stayed
    acquired for hours, freezing the worker entirely until the upstream
    session was finally recycled. Bedrest tests started failing too
    because they hit the same lock via real get_conn.

  Fix (v2): row-based worker_lease table. Atomic upsert with
    expires_at TTL guard. Auto-recovers on crash. Pool-agnostic.

These tests don't hit Postgres — they monkey-patch get_conn so we can
verify the structural contract independent of DB state:
  1. run_once attempts to upsert into worker_lease
  2. when the row already exists + not expired, run_once exits no-op
  3. when acquired, the lease is released via DELETE on the same holder_id
  4. release uses a (name + holder_id) guard so it can't stomp a
     successor lease holder
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List, Tuple
from unittest.mock import MagicMock

from app.db import telegram_worker


class _FakeCursor:
    """Records every execute() call, returns a programmable
    fetchone() value so we can simulate (a) acquired vs lost lease
    and (b) the row existing vs not."""

    def __init__(self, scripted_returns: List[Any], calls: List[Tuple[str, tuple]]):
        self._returns = list(scripted_returns)
        self._calls = calls
        self._last = None

    def __enter__(self): return self
    def __exit__(self, *a): return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._calls.append((sql, params))
        # Pop one scripted return per execute() so test order matches.
        self._last = self._returns.pop(0) if self._returns else None

    def fetchone(self): return self._last


class _FakeConn:
    def __init__(self, scripted_returns: List[Any]):
        self._returns = scripted_returns
        self.calls: List[Tuple[str, tuple]] = []

    def __enter__(self): return self
    def __exit__(self, *a): return None
    def cursor(self): return _FakeCursor(self._returns, self.calls)


def _patch_get_conn(monkeypatch, scripted_returns: List[Any]) -> _FakeConn:
    conn = _FakeConn(scripted_returns)

    @contextmanager
    def fake_get_conn(*_a, **_kw):
        yield conn

    monkeypatch.setattr(telegram_worker, "get_conn", fake_get_conn)
    return conn


def test_lease_acquired_proceeds_to_run(monkeypatch):
    """When the INSERT ... ON CONFLICT WHERE expired succeeds, the
    RETURNING clause echoes back our holder_id → run_once proceeds
    into the per-user scan path."""
    # Two execute() calls expected: acquire (RETURNS our holder_id)
    # + release (no return needed). We can't predict the holder_id, so
    # capture it from the actual call params and align fetchone() result.
    captured_holder = {}

    class _ConditionalReturn:
        """Returns the holder_id we observe being inserted, so the
        acquire path treats the lease as won."""
        def __call__(self, sql, params):
            if "INSERT INTO worker_lease" in sql:
                captured_holder["v"] = params[1]
                return (params[1],)
            return None

    cb = _ConditionalReturn()
    conn = _FakeConn([])

    # Override execute to feed dynamic returns based on the call.
    def execute(self, sql, params=()):
        self._calls.append((sql, params))
        self._last = cb(sql, params)
    monkeypatch.setattr(_FakeCursor, "execute", execute)

    @contextmanager
    def fake_get_conn(*_a, **_kw):
        yield conn

    monkeypatch.setattr(telegram_worker, "get_conn", fake_get_conn)
    locked_called = MagicMock(return_value={"users": 0})
    monkeypatch.setattr(telegram_worker, "_run_once_locked", locked_called)

    result = telegram_worker.run_once(dry_run=True)

    locked_called.assert_called_once()
    assert result.get("skipped_locked", 0) == 0
    # acquire + release SQL both fired.
    sqls = [s for s, _ in conn.calls]
    assert any("INSERT INTO worker_lease" in s for s in sqls)
    assert any("DELETE FROM worker_lease" in s for s in sqls)
    # The release was scoped to the holder_id we acquired with.
    delete_call = next(c for c in conn.calls if "DELETE" in c[0])
    assert delete_call[1] == (telegram_worker._LEASE_NAME, captured_holder["v"])


def test_lease_not_acquired_skips(monkeypatch):
    """When the lease row exists and is unexpired, INSERT ... ON
    CONFLICT WHERE clause fails to match → RETURNING yields nothing
    → run_once sees no holder_id echo → skips."""
    # First execute() = acquire attempt → returns None (no rows).
    _patch_get_conn(monkeypatch, [None])
    locked_called = MagicMock()
    monkeypatch.setattr(telegram_worker, "_run_once_locked", locked_called)

    result = telegram_worker.run_once(dry_run=True)

    locked_called.assert_not_called()
    assert result["skipped_locked"] == 1
    assert result["users"] == 0
    assert result["sent"] == 0


def test_release_uses_holder_id_guard(monkeypatch):
    """Releasing without the holder_id guard would stomp a successor.
    The DELETE WHERE name=%s AND holder_id=%s clause prevents it."""
    conn = _FakeConn([])
    captured_release = {}

    class _ExecScript:
        def __call__(self, sql, params):
            if "INSERT INTO worker_lease" in sql:
                return (params[1],)        # acquire wins
            if "DELETE FROM worker_lease" in sql:
                captured_release["params"] = params
            return None

    cb = _ExecScript()

    def execute(self, sql, params=()):
        self._calls.append((sql, params))
        self._last = cb(sql, params)
    monkeypatch.setattr(_FakeCursor, "execute", execute)

    @contextmanager
    def fake_get_conn(*_a, **_kw):
        yield conn

    monkeypatch.setattr(telegram_worker, "get_conn", fake_get_conn)
    monkeypatch.setattr(telegram_worker, "_run_once_locked",
                        lambda stats, dry: stats)

    telegram_worker.run_once(dry_run=True)

    p = captured_release["params"]
    assert p[0] == telegram_worker._LEASE_NAME
    # Holder ID is a uuid4 hex — 32 chars, no dashes.
    assert isinstance(p[1], str) and len(p[1]) == 32


def test_release_fires_even_on_inner_exception(monkeypatch):
    """The finally: _release_lease() must run even when the worker
    body raises, so a transient bug doesn't pin the lease until TTL."""
    conn = _FakeConn([])

    class _ExecScript:
        def __call__(self, sql, params):
            if "INSERT INTO worker_lease" in sql:
                return (params[1],)
            return None
    cb = _ExecScript()

    def execute(self, sql, params=()):
        self._calls.append((sql, params))
        self._last = cb(sql, params)
    monkeypatch.setattr(_FakeCursor, "execute", execute)

    @contextmanager
    def fake_get_conn(*_a, **_kw):
        yield conn

    monkeypatch.setattr(telegram_worker, "get_conn", fake_get_conn)

    def boom(*_a, **_kw):
        raise RuntimeError("simulated downstream failure")
    monkeypatch.setattr(telegram_worker, "_run_once_locked", boom)

    try:
        telegram_worker.run_once(dry_run=True)
    except RuntimeError:
        pass

    sqls = [s for s, _ in conn.calls]
    assert any("DELETE FROM worker_lease" in s for s in sqls), sqls
