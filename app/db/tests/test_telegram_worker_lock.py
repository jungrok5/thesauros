"""Telegram worker advisory-lock guard.

Pins the 2026-05-28 race-condition fix:

  Symptom: 4 enter-class alerts went out 2× each, ~1 second apart.
  Root cause: 6 parallel Analyze-Single-Ticker workflow dispatches
    each ran `python -m app.db.telegram_worker`. Each worker scanned
    ALL active signals (not just the analyzed ticker) and inserted
    `alerts` rows. Because the dedup check (`_already_alerted`) reads
    `alerts` before its own insert lands, two near-simultaneous
    workers both saw 0 prior alerts and both sent.

  Fix: pg_try_advisory_lock(K) at run_once entry. Second concurrent
    invocation returns False and exits as a no-op.

These tests don't hit Postgres — they monkeypatch get_conn so we can
verify the structural contract:
  1. run_once attempts to acquire pg_try_advisory_lock with a stable key
  2. when the lock isn't acquired, run_once exits without scanning users
  3. when the lock is acquired, it is released via pg_advisory_unlock
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List, Tuple
from unittest.mock import MagicMock

from app.db import telegram_worker


class _FakeCursor:
    def __init__(self, lock_acquired: bool, calls: List[Tuple[str, tuple]]):
        self._lock_acquired = lock_acquired
        self._calls = calls
        self._last_result: Any = None

    def __enter__(self): return self
    def __exit__(self, *a): return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            self._last_result = (self._lock_acquired,)
        elif "pg_advisory_unlock" in sql:
            self._last_result = (True,)
        else:
            self._last_result = None

    def fetchone(self) -> Any:
        return self._last_result


class _FakeConn:
    def __init__(self, lock_acquired: bool):
        self._lock_acquired = lock_acquired
        self.calls: List[Tuple[str, tuple]] = []

    def __enter__(self): return self
    def __exit__(self, *a): return None
    def cursor(self): return _FakeCursor(self._lock_acquired, self.calls)


def _patch_get_conn(monkeypatch, lock_acquired: bool) -> _FakeConn:
    conn = _FakeConn(lock_acquired)

    @contextmanager
    def fake_get_conn(*_a, **_kw):
        yield conn

    monkeypatch.setattr(telegram_worker, "get_conn", fake_get_conn)
    return conn


def test_lock_acquired_proceeds_to_run(monkeypatch):
    """When pg_try_advisory_lock returns True, run_once continues into
    the scan path (calling _run_once_locked)."""
    _patch_get_conn(monkeypatch, lock_acquired=True)
    locked_called = MagicMock(return_value={"users": 0})
    monkeypatch.setattr(telegram_worker, "_run_once_locked", locked_called)
    result = telegram_worker.run_once(dry_run=True)
    locked_called.assert_called_once()
    assert result.get("skipped_locked", 0) == 0


def test_lock_not_acquired_skips(monkeypatch):
    """When another session holds the lock, run_once exits as a no-op
    without touching the scan path."""
    _patch_get_conn(monkeypatch, lock_acquired=False)
    locked_called = MagicMock()
    monkeypatch.setattr(telegram_worker, "_run_once_locked", locked_called)
    result = telegram_worker.run_once(dry_run=True)
    locked_called.assert_not_called()
    assert result["skipped_locked"] == 1
    assert result["users"] == 0
    assert result["sent"] == 0


def test_lock_released_on_success(monkeypatch):
    """The session-scoped lock must be released via pg_advisory_unlock
    when the run completes, so the next workflow dispatch can acquire
    it cleanly."""
    conn = _patch_get_conn(monkeypatch, lock_acquired=True)
    monkeypatch.setattr(telegram_worker, "_run_once_locked",
                        lambda stats, dry: stats)
    telegram_worker.run_once(dry_run=True)
    sql_calls = [s for s, _ in conn.calls]
    assert any("pg_try_advisory_lock" in s for s in sql_calls), sql_calls
    assert any("pg_advisory_unlock" in s for s in sql_calls), sql_calls


def test_lock_released_on_exception(monkeypatch):
    """Even when the inner scan throws, the unlock must still fire so
    a transient bug doesn't permanently freeze the worker."""
    conn = _patch_get_conn(monkeypatch, lock_acquired=True)

    def boom(*_a, **_kw):
        raise RuntimeError("simulated downstream failure")

    monkeypatch.setattr(telegram_worker, "_run_once_locked", boom)
    try:
        telegram_worker.run_once(dry_run=True)
    except RuntimeError:
        pass
    sql_calls = [s for s, _ in conn.calls]
    assert any("pg_advisory_unlock" in s for s in sql_calls), sql_calls
