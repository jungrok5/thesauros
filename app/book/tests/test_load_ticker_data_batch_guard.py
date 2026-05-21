"""Regression test for the scan_daily timeout cascade fix.

Bug (2026-05-21): scan_daily iterates the full universe. For US tickers
without bars in DB, load_ticker_data() fell through to a live Naver
fetch — when Naver rate-limited GH Actions IPs every fetch hit the 10s
timeout, and the cumulative timeout blew the 75-min step ceiling.

Fix: env-gated opt-out. The daily-scan workflow sets
`THESAUROS_DISABLE_LIVE_FETCH=1` so load_ticker_data() returns None
immediately for US tickers missing from DB instead of trying Naver.

This test pins that behavior so future refactors don't accidentally
remove the guard.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.book import analyzer


def test_live_naver_fetch_disabled_when_env_set(monkeypatch):
    """With THESAUROS_DISABLE_LIVE_FETCH=1 (cron's scan_daily mode), a
    US ticker missing from DB must return None without hitting Naver."""
    monkeypatch.setenv("THESAUROS_DISABLE_LIVE_FETCH", "1")

    # Simulate "no rows in DB for AAPL" — get_conn yields a cursor that
    # fetches nothing.
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    with patch("app.db.get_conn", return_value=fake_conn):
        with patch("app.data.naver_bars.fetch_weekly") as mock_naver:
            result = analyzer.load_ticker_data("AAPL", years=2)

    assert result is None
    assert mock_naver.call_count == 0, (
        "batch mode must not issue any live Naver call"
    )


def test_live_naver_fetch_allowed_when_env_unset(monkeypatch):
    """Outside batch mode (e.g. ad-hoc /api/analyze/[ticker] call), the
    live fallback IS allowed — it's how just-watchlisted US tickers get
    their bars before the next cron pass."""
    monkeypatch.delenv("THESAUROS_DISABLE_LIVE_FETCH", raising=False)

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    with patch("app.db.get_conn", return_value=fake_conn):
        with patch("app.data.naver_bars.fetch_weekly", return_value=None) as mock_naver:
            analyzer.load_ticker_data("AAPL", years=2)

    assert mock_naver.call_count == 1, (
        "ad-hoc path must still try Naver — otherwise newly-watchlisted "
        "US tickers would have no bars until the next cron"
    )


def test_kr_ticker_never_uses_naver_fallback(monkeypatch):
    """KR tickers are fully populated by the FDR cron — even outside
    batch mode the Naver fallback must NOT be tried for them (Naver's
    US chart endpoint doesn't have KR data)."""
    monkeypatch.delenv("THESAUROS_DISABLE_LIVE_FETCH", raising=False)

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    with patch("app.db.get_conn", return_value=fake_conn):
        with patch("app.data.naver_bars.fetch_weekly") as mock_naver:
            result = analyzer.load_ticker_data("005930.KS", years=2)

    assert result is None
    assert mock_naver.call_count == 0
