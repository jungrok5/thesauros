"""Regression tests for ingest_market_investor_trend parse helpers.

The cron snapshot path runs once per day across both markets. Tests
exercise the value parsing + bizdate normalization on real Naver
samples + the corner cases that have bitten us elsewhere (signed
strings with commas, null fields, malformed bizdate). Network-dependent
fetch_one() is exercised in a separate live-probe test path.
"""
from app.db.ingest_market_investor_trend import (
    _parse_bizdate,
    _parse_signed_int,
)


class TestParseSignedInt:
    def test_positive_with_comma(self):
        assert _parse_signed_int("+36,146") == 36146

    def test_negative_with_comma(self):
        assert _parse_signed_int("-27,414") == -27414

    def test_no_sign(self):
        assert _parse_signed_int("381") == 381

    def test_empty_string(self):
        assert _parse_signed_int("") is None

    def test_none(self):
        assert _parse_signed_int(None) is None

    def test_garbage(self):
        assert _parse_signed_int("abc") is None

    def test_float_string(self):
        # Naver sometimes returns "1.5" for very small markets — accept it.
        assert _parse_signed_int("1.5") == 1

    def test_zero(self):
        assert _parse_signed_int("0") == 0


class TestParseBizdate:
    def test_valid(self):
        assert _parse_bizdate("20260528") == "2026-05-28"

    def test_none(self):
        assert _parse_bizdate(None) is None

    def test_empty(self):
        assert _parse_bizdate("") is None

    def test_wrong_length(self):
        assert _parse_bizdate("2026052") is None
        assert _parse_bizdate("202605288") is None

    def test_non_digit(self):
        assert _parse_bizdate("2026-05-28") is None
