"""Stooq EOD CSV parser tests.

These guard against regressions in the parser path (CSV format changes,
error-page detection, schema normalization to match naver_bars) so the
US fallback keeps working even when its primary source (Naver) is
fully blocked.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from app.data import stooq


def _csv_response(body: str, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = body
    return r


def test_fetch_weekly_parses_standard_csv():
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-05-12,150.0,155.0,148.0,153.5,12345678\n"
        "2026-05-19,154.0,158.0,152.0,157.0,11111111\n"
    )
    with patch.object(stooq.requests, "get", return_value=_csv_response(csv)):
        df = stooq.fetch_weekly("AAPL")

    assert df is not None
    assert list(df.columns) == [
        "date", "open", "high", "low", "close", "adj_close", "volume"
    ]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 153.5
    # adj_close mirrors close (matches naver_bars schema).
    assert (df["adj_close"] == df["close"]).all()
    # date is sorted ascending.
    assert df.iloc[0]["date"] < df.iloc[1]["date"]
    assert df.attrs["grain"] == "W"


def test_fetch_monthly_parses_csv():
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-03-31,140.0,150.0,135.0,148.0,99999\n"
    )
    with patch.object(stooq.requests, "get", return_value=_csv_response(csv)):
        df = stooq.fetch_monthly("MSFT")

    assert df is not None
    assert df.attrs["grain"] == "M"
    assert df.iloc[0]["close"] == 148.0


def test_no_data_response_returns_none():
    """Stooq returns the literal string 'No data' for unknown symbols.
    Must not crash the parser."""
    with patch.object(
        stooq.requests, "get", return_value=_csv_response("No data\n")
    ):
        df = stooq.fetch_weekly("NONEXISTENT")
    assert df is None


def test_html_rate_limit_page_returns_none():
    """When over the daily limit Stooq returns an HTML page. Must not
    be parsed as CSV (would silently produce garbage rows)."""
    html = "<html><body>Exceeded the daily hits limit</body></html>"
    with patch.object(stooq.requests, "get", return_value=_csv_response(html)):
        df = stooq.fetch_weekly("AAPL")
    assert df is None


def test_http_error_returns_none():
    with patch.object(
        stooq.requests, "get", return_value=_csv_response("", status=503)
    ):
        df = stooq.fetch_weekly("AAPL")
    assert df is None


def test_class_share_dot_translates_to_dash():
    """BRK.B → Stooq's 'brk-b.us'. Bug if we accidentally double-suffix
    or leave the dot (Stooq's URL parser breaks on dots inside symbol)."""
    captured: dict = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _csv_response("No data\n")

    with patch.object(stooq.requests, "get", side_effect=_fake_get):
        stooq.fetch_weekly("BRK.B")

    assert captured["params"]["s"] == "brk-b.us"


def test_network_failure_returns_none():
    """Stooq is the fallback for Naver — when Stooq itself fails the
    caller must just get None, not a raised exception (cron resilience)."""
    import requests as _requests
    with patch.object(
        stooq.requests, "get",
        side_effect=_requests.ConnectionError("dns fail")
    ):
        df = stooq.fetch_weekly("AAPL")
    assert df is None
