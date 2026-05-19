"""Tests for SEC EDGAR ingest parsers.

We exercise the pure-function parsing logic against fixture payloads that
mirror real SEC response shapes. No network. No DB. The DB upsert helpers
(`_upsert_fundamentals`, `_upsert_disclosures`) are intentionally NOT
tested here — they're trivial executemany wrappers and require a live
Supabase connection, covered by the smoke test against the ingest cron.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.data.ingest_sec import (
    TARGET_CONCEPTS,
    TARGET_FORMS,
    _extract_annual_facts,
    _extract_recent_filings,
)


# ---------------------------------------------------------------------
# companyfacts parser
# ---------------------------------------------------------------------

def _companyfacts_fixture() -> dict:
    """Minimal companyfacts JSON in the exact SEC shape."""
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2023-12-31", "val": 100, "fy": 2023,
                             "fp": "FY", "form": "10-K", "filed": "2024-02-01",
                             "accn": "0001-23-001"},
                            {"end": "2024-12-31", "val": 120, "fy": 2024,
                             "fp": "FY", "form": "10-K", "filed": "2025-02-01",
                             "accn": "0001-25-001"},
                            # Q1 row — must be filtered out
                            {"end": "2024-03-31", "val": 30, "fy": 2024,
                             "fp": "Q1", "form": "10-Q", "filed": "2024-05-01"},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"end": "2024-12-31", "val": 20, "fy": 2024,
                             "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
                        ]
                    }
                },
                # Concept outside TARGET_CONCEPTS — must be ignored
                "ResearchAndDevelopmentExpense": {
                    "units": {
                        "USD": [
                            {"end": "2024-12-31", "val": 5, "fy": 2024,
                             "fp": "FY"},
                        ]
                    }
                },
                # Wrong unit — must be ignored (we only keep USD + shares)
                "Revenues_NonUSD": {
                    "units": {
                        "EUR": [
                            {"end": "2024-12-31", "val": 999, "fy": 2024,
                             "fp": "FY"},
                        ]
                    }
                },
            }
        }
    }


def test_extract_annual_facts_keeps_only_fy():
    rows = _extract_annual_facts(_companyfacts_fixture())
    # Two FY rows for Revenues (2023, 2024) + one FY for NetIncomeLoss = 3.
    # Q1 row, off-target concept, EUR row all dropped.
    assert len(rows) == 3
    by_concept = {(c, fy): (v, u, f) for (c, fy, v, u, f) in rows}
    assert (("Revenues", 2023) in by_concept)
    assert (("Revenues", 2024) in by_concept)
    assert (("NetIncomeLoss", 2024) in by_concept)
    # Make sure values + filed dates round-trip correctly.
    val, unit, filed = by_concept[("Revenues", 2024)]
    assert val == pytest.approx(120.0)
    assert unit == "USD"
    assert filed == date(2025, 2, 1)


def test_target_concepts_constant_includes_core_set():
    # Sanity: a future refactor must not silently drop these critical
    # concepts — they're what the eval pipeline reads.
    for required in (
        "Revenues", "NetIncomeLoss", "OperatingIncomeLoss",
        "Assets", "Liabilities", "StockholdersEquity",
    ):
        assert required in TARGET_CONCEPTS


# ---------------------------------------------------------------------
# submissions parser
# ---------------------------------------------------------------------

def _submissions_fixture() -> dict:
    return {
        "cik": "0000320193",
        "filings": {
            "recent": {
                "form": ["10-K", "8-K", "4", "10-Q", "DEF 14A", "10-K/A"],
                "accessionNumber": [
                    "0000320193-25-000123",
                    "0000320193-25-000124",
                    "0000320193-25-000125",  # Form 4 — must be filtered
                    "0000320193-25-000126",
                    "0000320193-25-000127",
                    "0000320193-24-000999",
                ],
                "filingDate": [
                    "2025-02-01", "2025-03-01", "2025-04-01",
                    "2025-05-01", "2025-01-15", "2024-12-15",
                ],
                "primaryDocument": [
                    "aapl-10k.htm", "aapl-8k.htm", "form4.xml",
                    "aapl-10q.htm", "aapl-proxy.htm", "aapl-10ka.htm",
                ],
            }
        },
    }


def test_extract_recent_filings_filters_form4():
    out = _extract_recent_filings(_submissions_fixture(), "0000320193")
    # 6 input rows, 1 is Form 4 (not in TARGET_FORMS) → 5 expected.
    assert len(out) == 5
    forms = {row[2] for row in out}
    assert "4" not in forms
    assert {"10-K", "8-K", "10-Q", "DEF 14A", "10-K/A"} <= forms


def test_extract_recent_filings_builds_archives_url():
    out = _extract_recent_filings(_submissions_fixture(), "0000320193")
    # Find the 10-K row and verify the URL pattern: dashes stripped, cik
    # as integer (no padding), primary document appended.
    ten_k = next(row for row in out if row[2] == "10-K")
    rcept_no, _, _, filed, url = ten_k
    assert rcept_no == "0000320193-25-000123"
    assert filed == date(2025, 2, 1)
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000123/aapl-10k.htm"
    )


def test_extract_recent_filings_korean_label():
    out = _extract_recent_filings(_submissions_fixture(), "0000320193")
    labels = {row[1] for row in out}
    assert "연간보고서 (10-K)" in labels
    assert "주요사항 (8-K)" in labels
    assert "주총소집 (DEF 14A)" in labels


def test_target_forms_excludes_form4():
    # Regression: Form 4 (insider trades) was the original noise source —
    # if it ever creeps back in, this test fails.
    assert "4" not in TARGET_FORMS
    assert "3" not in TARGET_FORMS
    assert "10-K" in TARGET_FORMS
