"""Tests for macro/fetch.py Yahoo v8 chart parsing.

The fetch path bypasses the `yfinance` Python lib (which detects + blocks
cloud-IP traffic on GH Actions) by calling Yahoo's v8 chart endpoint
directly. We test that the JSON-shape parser turns a representative
response into the expected (date, value) DataFrame, including the
"timestamp + close-list-with-nulls" layout that v8 actually returns.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pandas as pd

from app.macro import fetch


def _ts(year: int, month: int, day: int) -> int:
    """UTC midnight epoch seconds — matches Yahoo's daily-interval ts."""
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def _yahoo_payload(*, with_null: bool = True) -> dict:
    """Minimal payload mirroring `query1.finance.yahoo.com/v8/finance/chart/...`."""
    closes = [100.0, None, 102.5] if with_null else [100.0, 101.0, 102.5]
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [
                        _ts(2026, 1, 2),
                        _ts(2026, 1, 3),
                        _ts(2026, 1, 6),
                    ],
                    "indicators": {
                        "quote": [
                            {"close": closes},
                        ],
                    },
                }
            ],
        }
    }


class _MockResponse:
    """Drop-in for requests.Response with just the bits we use."""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_fetch_yf_parses_v8_payload():
    with patch("app.macro.fetch.requests.get",
               return_value=_MockResponse(_yahoo_payload(with_null=False))):
        df = fetch._fetch_yf("^GSPC", start="2026-01-01")
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 3
    assert df.iloc[0]["date"] == date(2026, 1, 2)
    assert df.iloc[-1]["value"] == 102.5


def test_fetch_yf_drops_null_closes():
    """Yahoo emits None for non-trading-day gaps; those rows must be dropped
    (otherwise downstream `executemany` chokes on NULL value)."""
    with patch("app.macro.fetch.requests.get",
               return_value=_MockResponse(_yahoo_payload(with_null=True))):
        df = fetch._fetch_yf("^GSPC", start="2026-01-01")
    # 3 input rows, 1 null → 2 rows remain.
    assert len(df) == 2
    assert all(df["value"].notna())


def test_fetch_yf_handles_404_as_empty():
    """When Yahoo returns a non-200, we return an empty DataFrame so the
    enclosing `ingest_all` continues with the rest of the indicators.
    """
    with patch("app.macro.fetch.requests.get",
               return_value=_MockResponse({}, status_code=404)):
        df = fetch._fetch_yf("DOES.NOT.EXIST", start="2026-01-01")
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["date", "value"]


def test_fetch_yf_handles_error_payload():
    payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
    with patch("app.macro.fetch.requests.get",
               return_value=_MockResponse(payload)):
        df = fetch._fetch_yf("BAD.SYM", start="2026-01-01")
    assert df.empty
