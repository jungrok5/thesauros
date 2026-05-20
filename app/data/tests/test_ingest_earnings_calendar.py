"""Pure-function tests for earnings_calendar cadence seed.

The whole module is one rule: given today's date, return the next 4
KR periodic-report legal cutoffs. That's the entire surface to test —
boundary days (May 14 vs May 15 vs May 16) and year rollover.
"""
from __future__ import annotations

from datetime import date

from app.data.ingest_earnings_calendar import _next_expected_dates


class TestNextExpectedDates:
    def test_january_returns_q1_q2_q3_plus_next_FY(self):
        # 1월 → Q1 5/15, Q2 8/14, Q3 11/14 모두 미래.
        # FY 는 cadence 정의상 year_offset=1 → 2027-03-31 가 다음 FY.
        # (작년 사업보고서 3/31/2026 은 이미 지나서 제외 — 1월 5일 기준.)
        today = date(2026, 1, 5)
        out = _next_expected_dates(today)
        assert out == [
            (date(2026, 5, 15), "Q1"),
            (date(2026, 8, 14), "Q2"),
            (date(2026, 11, 14), "Q3"),
            (date(2027, 3, 31), "FY"),
        ]

    def test_day_before_cutoff_still_includes_it(self):
        today = date(2026, 5, 14)
        out = _next_expected_dates(today)
        # Q1 cutoff is 5/15 — must be in tomorrow's list.
        assert (date(2026, 5, 15), "Q1") in out

    def test_day_of_cutoff_includes_it(self):
        today = date(2026, 5, 15)
        out = _next_expected_dates(today)
        # Convention: cutoff DAY is still "upcoming" (filed by end of day).
        assert (date(2026, 5, 15), "Q1") in out

    def test_day_after_cutoff_drops_it(self):
        today = date(2026, 5, 16)
        out = _next_expected_dates(today)
        assert (date(2026, 5, 15), "Q1") not in out

    def test_late_year_pulls_from_next_year(self):
        today = date(2026, 12, 1)
        out = _next_expected_dates(today)
        # 12월 → 다음해 3/31 FY, 5/15 Q1, 8/14 Q2, 11/14 Q3
        assert out[0] == (date(2027, 3, 31), "FY")
        assert out[-1] == (date(2027, 11, 14), "Q3")

    def test_returns_exactly_four(self):
        for month in range(1, 13):
            out = _next_expected_dates(date(2026, month, 15))
            assert len(out) == 4, f"month {month} returned {len(out)}"

    def test_output_sorted_ascending(self):
        out = _next_expected_dates(date(2026, 6, 1))
        dates = [d for d, _ in out]
        assert dates == sorted(dates)
