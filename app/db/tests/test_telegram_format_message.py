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
