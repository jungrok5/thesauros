"""Tests for disclosure-alert formatting + classification.

Pure-function tests — no DB, no DART, no Telegram. The integration
path (watchlist → DART → telegram) gets exercised once a day by the
real cron and is observability-covered via the alerts table.
"""
from __future__ import annotations

from app.db.notify_disclosure_alerts import format_disclosure_message


class TestMessageHints:
    """Each "hint" line maps a DART report_nm keyword family to a
    plain-Korean 한 줄 평. These tests lock the mapping so a tweak
    to one of the strings can't silently silence the others.
    """

    def _msg(self, rn: str) -> str:
        return format_disclosure_message("삼성전자", "005930.KS", rn,
                                         "2026-05-20", "https://dart.fss.or.kr/")

    def test_buyback_hint(self):
        for rn in ("자기주식취득결과보고서", "자사주매입", "자사주 취득 결정"):
            m = self._msg(rn)
            assert "자사주" in m and "저평가" in m, rn

    def test_rights_offering_hint(self):
        m = self._msg("유상증자결정")
        assert "유상증자" in m and "희석" in m

    def test_cb_hint(self):
        for rn in ("전환사채권발행결정", "전환사채 발행"):
            m = self._msg(rn)
            assert "전환사채" in m and "희석" in m, rn

    def test_dividend_hint(self):
        m = self._msg("현금배당결정")
        assert "배당" in m and "권리락" in m

    def test_periodic_report_hint(self):
        for rn in ("사업보고서", "분기보고서", "반기보고서"):
            m = self._msg(rn)
            assert "실적" in m and "컨센" in m.lower() or "컨센서스" in m, rn

    def test_shareholder_change_hint(self):
        for rn in ("최대주주변경", "주식등의대량보유상황보고서", "5% 보고"):
            m = self._msg(rn)
            assert "지분" in m or "큰손" in m, rn

    def test_fair_disclosure_hint(self):
        m = self._msg("공정공시")
        assert "공정공시" in m and "가이던스" in m or "IR" in m

    def test_unknown_falls_through_to_generic(self):
        m = self._msg("뭔지모르는공시이름")
        assert "일반 공시" in m


class TestMessageStructure:
    """The Telegram message must always include ticker, name, report
    name, filed date, and a clickable link. Missing any of those =
    user can't make a decision from the message alone."""

    def test_message_includes_essentials(self):
        m = format_disclosure_message(
            "삼성전자", "005930.KS",
            "유상증자결정", "2026-05-20",
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260520001234",
        )
        assert "삼성전자" in m
        assert "005930.KS" in m
        assert "유상증자결정" in m
        assert "2026-05-20" in m
        assert "dart.fss.or.kr" in m
        assert "<a href" in m  # clickable link

    def test_handles_missing_name_gracefully(self):
        # If ticker → name lookup fails, fall back to ticker as the title.
        m = format_disclosure_message("", "005930.KS", "공시",
                                      "2026-05-20", "http://x")
        assert "005930.KS" in m
        # Empty name not concatenated into the title
        assert "<b></b>" not in m
