"""Tests for cron_health deadline calendar math.

The alert fires when `analyze_results.updated_at` is older than the
expected post-cron deadline. Getting the deadline wrong in either
direction is bad: too lax → users see stale data without us knowing;
too strict → spurious 3am Telegram alerts for the admin. Pin the
cases here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.cron_health import expected_kr_cutoff


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_weekday_after_0830_uses_today() -> None:
    # Tuesday 2026-05-19 10:00 UTC — past today's 08:30 deadline.
    now = _utc("2026-05-19T10:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-19T08:30:00")


def test_weekday_before_0830_falls_back_to_prior_weekday() -> None:
    # Tuesday 2026-05-19 07:00 UTC — before today's deadline, so the
    # most recent "expected" data is from Monday.
    now = _utc("2026-05-19T07:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-18T08:30:00")


def test_monday_before_0830_falls_back_to_prior_friday() -> None:
    # Monday 2026-05-18 07:00 UTC — last weekday before is Friday 5/15.
    now = _utc("2026-05-18T07:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-15T08:30:00")


def test_saturday_returns_friday() -> None:
    # Saturday 2026-05-23 12:00 UTC — Friday is the most recent run.
    now = _utc("2026-05-23T12:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-22T08:30:00")


def test_sunday_returns_friday() -> None:
    now = _utc("2026-05-24T03:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-22T08:30:00")


def test_friday_after_0830_uses_today() -> None:
    now = _utc("2026-05-22T09:00:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-22T08:30:00")


def test_exactly_at_0830_uses_today() -> None:
    # Boundary: at exactly 08:30 we count today as the expected cycle.
    now = _utc("2026-05-19T08:30:00")
    cutoff = expected_kr_cutoff(now)
    assert cutoff == _utc("2026-05-19T08:30:00")
