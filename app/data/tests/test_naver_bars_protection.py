"""Regression tests for the protective layers added to naver_bars.

These tests guard against the failure mode that caused the 2026-05-21
cron meltdown:

  - Naver started rate-limiting GH Actions Azure IPs, causing every
    fetch to hit the 10s timeout.
  - With no backoff/circuit-breaker, a single scan_daily run would issue
    thousands of timing-out requests back-to-back and blow the 75-min
    step ceiling.

We test the layers in isolation by mocking `requests.get` and patching
out the token bucket + jitter sleep so the tests run instantly (no real
network, no real waits).
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest
import requests

from app.data import naver_bars


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with a clean circuit + full token bucket."""
    naver_bars.reset_state_for_tests()
    yield
    naver_bars.reset_state_for_tests()


@pytest.fixture
def _no_throttle():
    """Patch out the token bucket + jitter so failure-path tests don't
    have to fight refill timing. Tests of the throttle layer itself
    don't use this fixture."""
    with patch.object(naver_bars, "_acquire_token", lambda: None):
        with patch.object(naver_bars, "_sleep_jitter", lambda: None):
            with patch.object(naver_bars.time, "sleep", lambda *_: None):
                yield


def _ok_response(payload: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload or {"priceInfos": []}
    return r


# ---------------------------------------------------------------------
# Layer 4 — Circuit breaker
# ---------------------------------------------------------------------

def test_circuit_opens_after_consecutive_failures(_no_throttle):
    """THRESHOLD consecutive timeouts opens the breaker; subsequent
    calls fast-fail without hitting the network."""
    with patch.object(
        naver_bars.requests, "get", side_effect=requests.Timeout("rate-limit")
    ) as mock_get:
        # Drive enough failures to trip the breaker. Each _fetch retries
        # up to MAX_RETRIES + 1 times — every retry is a failure, so
        # one call is usually enough to cross THRESHOLD.
        while not naver_bars.is_circuit_open():
            naver_bars._fetch("AAPL.O", "weekCandle", 2)

        call_count_at_open = mock_get.call_count

        # Now a new call must NOT issue any HTTP request (fast-fail).
        result = naver_bars._fetch("MSFT.O", "weekCandle", 2)
        assert result is None
        assert mock_get.call_count == call_count_at_open, (
            "post-open fetch must not hit the network"
        )


def test_circuit_closes_on_success():
    """Success after partial failures resets the consecutive-failure
    counter, so sporadic timeouts don't accumulate into a trip."""
    for _ in range(naver_bars._CB_THRESHOLD - 1):
        naver_bars._record_failure()
    assert not naver_bars.is_circuit_open()

    naver_bars._record_success()
    # Counter reset — would now need full THRESHOLD failures again.
    for _ in range(naver_bars._CB_THRESHOLD - 1):
        naver_bars._record_failure()
    assert not naver_bars.is_circuit_open()


def test_is_circuit_open_callable_from_ingest():
    """ingest_bars uses is_circuit_open() to skip Naver entirely once
    the breaker trips, so callers must be able to query it cheaply."""
    assert naver_bars.is_circuit_open() is False

    # Force open via the internal API and verify the predicate reports it.
    with naver_bars._lock:
        naver_bars._circuit_open_until = time.monotonic() + 60

    assert naver_bars.is_circuit_open() is True


def test_try_suffixes_aborts_when_circuit_opens_midway(_no_throttle):
    """_try_suffixes loops over .O/.K/.A; once Naver trips mid-loop the
    remaining suffix probes must be skipped (otherwise we pay 3× timeout
    cost per ticker)."""
    # Pre-open the circuit so the first call already fast-fails.
    with naver_bars._lock:
        naver_bars._circuit_open_until = time.monotonic() + 60

    with patch.object(naver_bars.requests, "get") as mock_get:
        result = naver_bars._try_suffixes("AAPL", "weekCandle", 2)
        assert result is None
        assert mock_get.call_count == 0, (
            "circuit-open must short-circuit all 3 suffix attempts"
        )


# ---------------------------------------------------------------------
# Layer 2 — Backoff on timeout
# ---------------------------------------------------------------------

def test_backoff_retries_on_timeout(_no_throttle):
    """A transient timeout retries up to NAVER_BACKOFF_RETRIES times,
    then gives up. We verify the retry count, not the actual delay
    (sleep patched to no-op)."""
    with patch.object(
        naver_bars.requests, "get", side_effect=requests.Timeout()
    ) as mock_get:
        naver_bars._fetch("AAPL.O", "weekCandle", 2)

    # First attempt + retries = MAX_RETRIES + 1 calls.
    assert mock_get.call_count == naver_bars._BACKOFF_MAX_RETRIES + 1


def test_backoff_recovers_after_one_timeout(_no_throttle):
    """Recovers from a single transient timeout — typical case after a
    Naver hiccup. No circuit-breaker tripping for one-offs."""
    side_effects = [requests.Timeout(), _ok_response()]
    with patch.object(naver_bars.requests, "get", side_effect=side_effects):
        naver_bars._fetch("AAPL.O", "weekCandle", 2)

    # _consecutive_failures should be 0 after the success on retry.
    with naver_bars._lock:
        assert naver_bars._consecutive_failures == 0


# ---------------------------------------------------------------------
# Layer 1 — Token bucket
# ---------------------------------------------------------------------

def test_token_bucket_caps_burst_rate(monkeypatch):
    """With the bucket drained, the next call must wait (real-time
    refill). We use a small bucket + high RPM so the test completes
    quickly without patching time."""
    monkeypatch.setattr(naver_bars, "_NAVER_RPM", 600)   # 10/sec
    monkeypatch.setattr(naver_bars, "_TOKEN_BUCKET_CAP", 2)
    naver_bars.reset_state_for_tests()

    # Drain the bucket: first 2 calls return instantly.
    t0 = time.monotonic()
    naver_bars._acquire_token()
    naver_bars._acquire_token()
    drain_dt = time.monotonic() - t0
    assert drain_dt < 0.05, "burst inside bucket capacity must be ~free"

    # 3rd call must wait for refill (~0.1s at 10/sec).
    t1 = time.monotonic()
    naver_bars._acquire_token()
    wait_dt = time.monotonic() - t1
    assert wait_dt >= 0.05, (
        f"over-budget call should have throttled, but only waited {wait_dt:.3f}s"
    )


def test_token_bucket_thread_safe(monkeypatch):
    """The bucket uses a single Lock; concurrent calls must not
    over-issue tokens. We pin total acquisitions to bucket capacity in
    a near-instant burst and verify the count matches expectation."""
    monkeypatch.setattr(naver_bars, "_NAVER_RPM", 60)   # 1/sec
    monkeypatch.setattr(naver_bars, "_TOKEN_BUCKET_CAP", 3)
    naver_bars.reset_state_for_tests()

    import threading

    acquired: list[float] = []
    barrier = threading.Barrier(3)

    def _worker() -> None:
        barrier.wait()
        naver_bars._acquire_token()
        acquired.append(time.monotonic())

    threads = [threading.Thread(target=_worker) for _ in range(3)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0
    # All 3 fit in the initial burst capacity of 3 → should finish fast.
    assert len(acquired) == 3
    assert elapsed < 0.3, (
        f"3 workers × 3-capacity bucket should burst, took {elapsed:.2f}s"
    )
