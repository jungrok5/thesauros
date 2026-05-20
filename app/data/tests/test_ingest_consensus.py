"""Pure-function tests for ingest_consensus parsing helpers.

We don't exercise the Naver HTTP call (mocked via _naver_get).  Only
the value-coercion helper is pure enough to lock in. The Naver
endpoint payload shape is covered by an integration-style smoke test
that runs as part of the weekly cron's --tickers samsung dry-run.
"""
from __future__ import annotations

from app.data.ingest_consensus import _to_float


class TestToFloat:
    def test_plain_number(self):
        assert _to_float("42571") == 42571.0

    def test_comma_separated(self):
        # Naver returns "6,789,614" for revenue values
        assert _to_float("6,789,614") == 6789614.0

    def test_decimal(self):
        assert _to_float("51.01") == 51.01

    def test_zero(self):
        assert _to_float("0") == 0.0
        assert _to_float(0) == 0.0

    def test_negative(self):
        assert _to_float("-1.5") == -1.5

    def test_dash_is_none(self):
        # Naver uses "-" for "not available" cells
        assert _to_float("-") is None

    def test_empty_is_none(self):
        assert _to_float("") is None
        assert _to_float(None) is None

    def test_garbage_is_none(self):
        assert _to_float("N/A") is None
        assert _to_float("abc") is None
