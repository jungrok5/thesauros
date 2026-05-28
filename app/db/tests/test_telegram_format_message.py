"""format_message regression — guards the user-facing copy contract.

Why this test exists: 2026-05-22 cron sent jungrok5 a real enter alert
("🟢 TSLA Tesla, Inc.  - Common Stock · 매수 / 추세 우호 정렬 (매수) / 강도 0.63")
and the user couldn't tell:
  - which alert preference toggle fired it (just an emoji, no Korean label)
  - what action the signal implied (one descriptive phrase, no ask)
  - where to inspect the underlying data (no deep link to the stock page)

The redesigned `format_message` must always:
  1. Show the Korean alert_type label in the title (진입 신호 / 청산
     신호 / 추가매수 / 경고 / 목표가 / 손절가).
  2. Pair the signal phrase with a book-tone action ask ("점검",
     "검토", "원칙대로 매도") — NEVER "사세요" / "팔아라" hype.
  3. Render a `<a href="…/stocks/{ticker}">` deep link.
  4. Surface the trigger toggle as a footer line so the user can
     turn it off if it's noisy.

These four contract checks are the regression gates. Anything else in
the copy is fair game to iterate on without breaking the test.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.db import telegram_worker


@pytest.fixture(autouse=True)
def _stub_db_lookups():
    """format_message reaches into Supabase for analyze_results +
    investor_flow. These tests are about the formatting contract, not
    DB integration — stub them out so the tests run without network."""
    with patch.object(telegram_worker, "_analyze_blob", return_value=None):
        with patch.object(telegram_worker, "_flow_5d", return_value=None):
            yield


def _enter_sig() -> Dict[str, Any]:
    return {
        "signal_type": "action_buy",
        "strength": 0.85,
        "params": {"confidence": 0.75},
    }


# ---------------------------------------------------------------------
# Contract — Korean alert_type label
# ---------------------------------------------------------------------

@pytest.mark.parametrize("alert_type,expected_label", [
    ("enter",   "진입 신호"),
    ("pyramid", "추가매수"),
    ("warn",    "경고"),
    ("exit",    "청산 신호"),
    ("target",  "목표가"),
    ("stop",    "손절가"),
])
def test_title_contains_korean_alert_label(alert_type, expected_label):
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", alert_type, _enter_sig(),
    )
    first_line = msg.splitlines()[0]
    assert expected_label in first_line, (
        f"alert_type={alert_type!r} title should contain {expected_label!r}, "
        f"got: {first_line!r}"
    )


def test_title_includes_ticker_and_name():
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    assert "005930.KS" in msg
    assert "삼성전자" in msg


def test_title_trims_naver_common_stock_suffix():
    """Naver pads US names with '  - Common Stock'. Without trimming,
    titles read 'TSLA Tesla, Inc.  - Common Stock · 진입 신호' — noise
    that crowds out the signal label on small phone screens."""
    msg = telegram_worker.format_message(
        "TSLA", "Tesla, Inc.  - Common Stock", "enter", _enter_sig(),
    )
    first_line = msg.splitlines()[0]
    assert "Common Stock" not in first_line, (
        f"common-stock suffix should be trimmed; title was: {first_line!r}"
    )
    assert "Tesla, Inc." in first_line


# ---------------------------------------------------------------------
# Contract — Action ask (책-tone, not hype)
# ---------------------------------------------------------------------

def test_message_contains_action_ask():
    """Each alert_type has its own action ask. The second line of the
    message pairs the signal phrase with that ask via an em-dash, so a
    user reading just the first two lines can answer 'what should I
    do?' without scrolling."""
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    # Second line is the phrase — action_ask pair.
    second = msg.splitlines()[1]
    assert "점검" in second or "검토" in second, (
        f"action ask missing from line 2: {second!r}"
    )


def test_no_hype_words_in_message():
    """Book tone: 매매는 안 할수록 좋고 좋은 자리에서만. Never
    instruct users to '지금 사세요' / '팔아라' — only soft 점검/검토/
    원칙대로 verbs."""
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    banned = ("사세요", "지금 사", "팔아라", "꼭 사", "무조건")
    for word in banned:
        assert word not in msg, f"hype word {word!r} leaked into alert"


# ---------------------------------------------------------------------
# Contract — Deep link to stock page
# ---------------------------------------------------------------------

def test_message_contains_stock_detail_link(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://thesauros2026.vercel.app")
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    expected_href = 'href="https://thesauros2026.vercel.app/stocks/005930.KS"'
    assert expected_href in msg, (
        f"stock-detail deep link missing from message: {msg!r}"
    )
    # Anchor text should be Korean + arrow so it's obviously a link.
    assert "상세 분석 보기" in msg


def test_base_url_strips_trailing_slash(monkeypatch):
    """A WEB_BASE_URL with trailing slash must not produce a double-
    slash URL like 'https://host.com//stocks/X' (browsers handle it
    but Telegram link previews don't normalize)."""
    monkeypatch.setenv("WEB_BASE_URL", "https://example.com/")
    msg = telegram_worker.format_message(
        "AAPL", "Apple Inc.", "enter", _enter_sig(),
    )
    assert "//stocks" not in msg
    assert "https://example.com/stocks/AAPL" in msg


def test_default_base_url_when_env_unset(monkeypatch):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    msg = telegram_worker.format_message(
        "AAPL", "Apple Inc.", "enter", _enter_sig(),
    )
    assert "thesauros2026.vercel.app/stocks/AAPL" in msg


# ---------------------------------------------------------------------
# Contract — Footer names the trigger toggle
# ---------------------------------------------------------------------

def test_message_names_alert_preference_in_footer():
    """The footer must spell out which alert preference toggled this
    so a user who wants to silence a noisy alert type knows what to
    flip off on /settings."""
    msg = telegram_worker.format_message(
        "AAPL", "Apple Inc.", "warn", _enter_sig(),
    )
    assert '알림 설정 "경고"' in msg, (
        "warn alerts should footer-reference '경고' setting; got: " + msg
    )


# ---------------------------------------------------------------------
# Smoke — full message looks roughly like the docstring example
# ---------------------------------------------------------------------

def test_full_message_smoke(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://thesauros2026.vercel.app")
    msg = telegram_worker.format_message(
        "TSLA", "Tesla, Inc.  - Common Stock", "enter",
        {
            "signal_type": "action_buy",
            "strength": 0.66,
            "params": {"confidence": 0.65},
        },
    )
    # Required elements present.
    for needle in (
        "🟢", "진입 신호", "TSLA", "Tesla, Inc.",
        "강도 0.66",
        "🔔 알림 설정",
        "상세 분석 보기",
        "vercel.app/stocks/TSLA",
    ):
        assert needle in msg, f"{needle!r} missing from rendered message"


# ---------------------------------------------------------------------
# Contract — eligibility reflection (TSLA-style incident gate)
# ---------------------------------------------------------------------

def test_conditional_eligibility_downgrades_title_badge():
    """When the analyzer eligibility says CONDITIONAL — 자리 지남, the
    enter-class alert must downgrade visually (badge swap + label
    suffix) so the user can tell at a glance it's not a clean buy."""
    blob = {
        "trend": {"weekly": {"above_ma_10": True, "alignment_score": 1.0},
                  "monthly": {"above_ma_10": True, "alignment_score": 0.7}},
        "eligibility": {
            "grade": "CONDITIONAL",
            "icon": "⚠️",
            "headline": "오늘 매수 자격: 조건부 — 자리 지남",
            "body": "추세는 살아있지만 신규 매수 자리는 한참 지남.",
            "reason_code": "stretch_hold",
        },
    }
    with patch.object(telegram_worker, "_analyze_blob", return_value=blob):
        with patch.object(telegram_worker, "_flow_5d", return_value=None):
            msg = telegram_worker.format_message(
                "TSLA", "Tesla, Inc.", "enter", _enter_sig(),
            )
    first_line = msg.splitlines()[0]
    assert "⚠️" in first_line, f"downgrade icon missing: {first_line!r}"
    assert "(조건부)" in first_line, f"label not tagged 조건부: {first_line!r}"
    assert "오늘 매수 자격: 조건부 — 자리 지남" in msg, (
        "page's eligibility headline must appear in message"
    )


def test_ok_eligibility_keeps_normal_badge():
    """OK eligibility passes through unchanged — green badge, no
    (조건부) suffix, but the page's "매수 자격: 가능" headline still
    surfaces so the alert and page agree word-for-word."""
    blob = {
        "trend": {"weekly": {"above_ma_10": True, "alignment_score": 1.0}},
        "eligibility": {
            "grade": "OK", "icon": "✅",
            "headline": "오늘 매수 자격: 가능 (매수)",
            "body": "책 정신상 매수 자리.",
            "reason_code": None,
        },
    }
    with patch.object(telegram_worker, "_analyze_blob", return_value=blob):
        with patch.object(telegram_worker, "_flow_5d", return_value=None):
            msg = telegram_worker.format_message(
                "TSLA", "Tesla, Inc.", "enter", _enter_sig(),
            )
    first_line = msg.splitlines()[0]
    assert "🟢" in first_line, "OK grade should keep the green enter badge"
    assert "(조건부)" not in first_line
    assert "오늘 매수 자격: 가능 (매수)" in msg


def test_message_falls_back_when_eligibility_missing():
    """analyze_results rows written before the eligibility field
    existed must still render with the generic phrase + action ask."""
    blob = {
        "trend": {"weekly": {"above_ma_10": True, "alignment_score": 1.0}},
        # NB: no `eligibility` key
    }
    with patch.object(telegram_worker, "_analyze_blob", return_value=blob):
        with patch.object(telegram_worker, "_flow_5d", return_value=None):
            msg = telegram_worker.format_message(
                "TSLA", "Tesla, Inc.", "enter", _enter_sig(),
            )
    # Falls back to the original "추세 우호 정렬 (매수) — 지금 자리인지 점검"
    assert "지금 자리인지 점검" in msg


def test_month_end_week_label_appears(monkeypatch):
    """When the current week's Friday is the LAST Friday of its calendar
    month, the alert should remind users to check 월봉 신호 too — that's
    the book's '월말 1회 확인' rule (2부 3장) embedded in weekly-scan's
    existing alert. No dedicated monthly cron needed."""
    from datetime import date
    import app.db.telegram_worker as tw
    # Pick a Friday that's the last Friday of its month. 2026-05-29 is
    # a Friday; the next Friday (2026-06-05) is in June → month-end.
    monkeypatch.setattr(
        tw, "_is_month_end_week", lambda today=None: True,
    )
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    assert "월말 주" in msg
    assert "월봉 240MA" in msg


def test_month_end_label_absent_in_other_weeks(monkeypatch):
    """Non-month-end weeks must NOT carry the extra nudge — otherwise
    it loses meaning."""
    import app.db.telegram_worker as tw
    monkeypatch.setattr(
        tw, "_is_month_end_week", lambda today=None: False,
    )
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    assert "월말 주" not in msg


def test_is_month_end_week_recognizes_last_friday():
    """Direct check of the calendar predicate (independent of mocks).
    2026-05-29 is a Friday; the next Friday (2026-06-05) is in June →
    last Friday of May. 2026-05-22 is also Friday but 05-29 is later
    same month → NOT the last."""
    from datetime import date
    from app.db.telegram_worker import _is_month_end_week
    assert _is_month_end_week(date(2026, 5, 29)) is True
    assert _is_month_end_week(date(2026, 5, 22)) is False


def test_exit_class_alerts_ignore_eligibility():
    """exit/warn/stop alerts are about negative signals — never gated
    or downgraded by buy eligibility (the user needs to know about
    a SELL signal regardless of whether they 'could have bought')."""
    blob = {
        "trend": {"weekly": {"above_ma_10": False, "alignment_score": 0.0}},
        "eligibility": {
            "grade": "CONDITIONAL", "icon": "⚠️",
            "headline": "오늘 매수 자격: 조건부",
            "body": "...",
            "reason_code": "stretch_hold",
        },
    }
    with patch.object(telegram_worker, "_analyze_blob", return_value=blob):
        with patch.object(telegram_worker, "_flow_5d", return_value=None):
            msg = telegram_worker.format_message(
                "TSLA", "Tesla, Inc.", "exit",
                {"signal_type": "action_sell", "strength": 0.8,
                 "params": {}},
            )
    first_line = msg.splitlines()[0]
    # Original exit badge kept (🔴), no 조건부 suffix.
    assert "🔴" in first_line
    assert "청산 신호" in first_line
    assert "(조건부)" not in first_line


# ---------------------------------------------------------------------
# Contract — 2026-05-27 redesign: [source] tag + 다음 단계 guide
# ---------------------------------------------------------------------

@pytest.mark.parametrize("source,bracket", [
    ("관심", "[관심]"),
    ("보유", "[보유]"),
])
def test_source_tag_appears_in_title(source, bracket):
    """The header must tell the user which list this came from so the
    same body wording works for 관심 / 보유. Originally also covered
    [모의투자] when paper-buy used a separate source tag; paper feature
    was dropped 2026-05-28 (replaced by watchlist.entry_price snapshot)
    so only 관심/보유 remain. format_message still accepts arbitrary
    source strings — the renderer doesn't gate."""
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(), source=source,
    )
    first_line = msg.splitlines()[0]
    assert bracket in first_line, (
        f"source={source!r} title should contain {bracket!r}, "
        f"got: {first_line!r}"
    )


def test_source_omitted_when_none_for_backwards_compat():
    """Legacy callers pass source=None — must render without bracket
    so older code paths keep their original title shape."""
    msg = telegram_worker.format_message(
        "005930.KS", "삼성전자", "enter", _enter_sig(),
    )
    first_line = msg.splitlines()[0]
    assert "[" not in first_line.split("진입 신호")[0], (
        "no source tag should appear when source=None; "
        f"got: {first_line!r}"
    )


def test_enter_class_alerts_carry_next_steps_guide():
    """Beginner users keep asking 'alert came, now what?'. Enter-class
    alerts must spell out 1) 차트 확인 2) 분할 매수 3) 손절 — the
    book's three-step entry."""
    for atype in ("enter", "pyramid"):
        msg = telegram_worker.format_message(
            "005930.KS", "삼성전자", atype, _enter_sig(), source="관심",
        )
        assert "다음 단계:" in msg, f"{atype}: 다음 단계 block missing"
        assert "차트" in msg and "분할 매수" in msg and "손절" in msg, (
            f"{atype}: three-step entry guide incomplete"
        )


def test_exit_class_alerts_have_no_next_steps_guide():
    """Exit/warn/target/stop already carry their own action wording —
    don't double up with the entry-style guide that'd be confusing."""
    for atype in ("exit", "warn", "target", "stop"):
        msg = telegram_worker.format_message(
            "005930.KS", "삼성전자", atype, _enter_sig(), source="보유",
        )
        assert "다음 단계:" not in msg, (
            f"{atype}: 다음 단계 should be enter-class only, "
            f"but appeared in: {msg}"
        )


def test_friday_close_reminder_on_every_alert():
    """매 알림에 '매수 결정은 금요일 종가 기준' reminder 가 들어가야
    한다. 사용자가 일중 흔들림에 panic-trade 하는 패턴을 매 알림에서
    nudge — 한 줄이라 spam 아님."""
    for atype in ("enter", "pyramid", "warn", "exit", "target", "stop"):
        msg = telegram_worker.format_message(
            "005930.KS", "삼성전자", atype, _enter_sig(), source="관심",
        )
        assert "금요일" in msg and "일중 흔들림" in msg, (
            f"{atype}: Friday-close reminder missing in: {msg}"
        )

