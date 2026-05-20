"""Pure-function tests for the DART majorstock (5%) ingest.

No network, no DB — we exercise:
  - holder classification (NPS / AMC / FUND / OTHER detection)
  - safe-int / safe-float coercion of DART's stringy comma-separated
    numbers ("1,199,285,813")
"""
from __future__ import annotations

from app.data.ingest_institutional_ownership import (
    _classify,
    _to_int,
    _to_float,
)


# ---------------------------------------------------------------------
# Holder classification
# ---------------------------------------------------------------------

class TestClassify:
    def test_nps_by_full_name(self):
        assert _classify("국민연금공단") == "NPS"

    def test_nps_short_form_still_matched(self):
        # Internal substring rule — 국민연금 appears in any variant.
        assert _classify("국민연금") == "NPS"

    def test_amc_korean(self):
        assert _classify("미래에셋자산운용") == "AMC"
        assert _classify("삼성자산운용") == "AMC"
        assert _classify("한국투자증권") == "AMC"

    def test_amc_english(self):
        assert _classify("BlackRock Investment Management") == "AMC"

    def test_fund_keywords(self):
        assert _classify("Templeton Capital Fund") == "FUND"

    def test_other_when_no_match(self):
        assert _classify("Random Person") == "OTHER"
        assert _classify("이재용") == "OTHER"

    def test_empty(self):
        assert _classify("") == "OTHER"
        assert _classify(None) == "OTHER"  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Safe-int / safe-float — DART returns "1,199,285,813" + occasional "-"
# ---------------------------------------------------------------------

class TestCoercion:
    def test_int_with_commas(self):
        assert _to_int("1,199,285,813") == 1_199_285_813

    def test_int_zero(self):
        assert _to_int("0") == 0

    def test_int_none(self):
        assert _to_int(None) is None
        assert _to_int("") is None
        assert _to_int("-") is None

    def test_float_pct(self):
        assert _to_float("20.09") == 20.09
        assert _to_float("0.00") == 0.0

    def test_float_negative(self):
        assert _to_float("-0.05") == -0.05

    def test_float_with_commas(self):
        # Rare but possible if DART ever returned "1,234.56"
        assert _to_float("1,234.56") == 1234.56

    def test_float_none(self):
        assert _to_float("") is None
        assert _to_float("-") is None
        assert _to_float(None) is None
