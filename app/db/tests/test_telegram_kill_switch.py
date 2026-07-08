"""Regression tests for the Telegram master kill switch.

Telegram alerts were paused 2026-07-08. The pause is implemented as a
default-off env gate (``TELEGRAM_ALERTS_ENABLED``) checked inside every
low-level Telegram sender, so a single flag turns the whole thing on or
off. These tests pin that behaviour so a future edit can't silently
re-open the firehose (or break the re-enable path).
"""
from __future__ import annotations

import app.db.telegram_worker as tw
import app.db.cron_health as ch


# ---- telegram_alerts_enabled() env parsing --------------------------------

def test_disabled_by_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALERTS_ENABLED", raising=False)
    assert tw.telegram_alerts_enabled() is False


def test_disabled_for_falsey_values(monkeypatch):
    for val in ("", "0", "false", "no", "off", "disabled", " "):
        monkeypatch.setenv("TELEGRAM_ALERTS_ENABLED", val)
        assert tw.telegram_alerts_enabled() is False, val


def test_enabled_for_truthy_values(monkeypatch):
    for val in ("1", "true", "TRUE", "Yes", "on", " on "):
        monkeypatch.setenv("TELEGRAM_ALERTS_ENABLED", val)
        assert tw.telegram_alerts_enabled() is True, val


# ---- send_telegram short-circuits when disabled ---------------------------

def test_worker_send_skips_network_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALERTS_ENABLED", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")

    def boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("network hit while alerts disabled")

    monkeypatch.setattr(tw.requests, "post", boom)
    assert tw.send_telegram("123", "hi") is False


def test_cron_health_send_skips_network_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALERTS_ENABLED", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    import requests

    def boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("network hit while alerts disabled")

    monkeypatch.setattr(requests, "post", boom)
    assert ch.send_telegram("123", "hi") is False


# ---- send_telegram actually sends once re-enabled -------------------------

class _FakeResp:
    ok = True
    status_code = 200
    text = "{}"

    def json(self):
        return {}


def test_worker_send_hits_network_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALERTS_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    calls = {}

    def fake_post(url, *a, **k):
        calls["url"] = url
        return _FakeResp()

    monkeypatch.setattr(tw.requests, "post", fake_post)
    assert tw.send_telegram("123", "hi") is True
    assert "sendMessage" in calls["url"]
