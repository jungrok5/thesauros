"""Regression tests for the daily-scan lifecycle pings.

Background: 2026-05-22 the admin wanted a heartbeat so they'd see "cron
started" / "cron finished" telegram pings instead of having to open
GitHub Actions to know what happened.

These tests pin the rules that matter:
  1. start / end commands route their messages through the same
     admin-discovery + send helper as `cron_health.py` (single source
     for "who is admin")
  2. end command's status flag maps onto the right header (✅ / ❌ / 🟡)
  3. baseline diff math (DB MB, alert counts) shows up in the end
     message when a start snapshot was written
  4. neither command raises when GH env vars are absent (local
     iteration uses the same module)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db import notify_admin_cron


@pytest.fixture
def fake_baseline_path(tmp_path, monkeypatch):
    """Force _snapshot_path() to live inside a per-test temp dir so a
    test's writes don't leak into the next."""
    path = tmp_path / "cron_start_test.json"
    monkeypatch.setattr(notify_admin_cron, "_snapshot_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    """All tests use synthetic baseline data — the DB shouldn't be
    touched. Stub the cheapest layer (the helpers that hit Postgres)."""
    monkeypatch.setattr(notify_admin_cron, "_capture_baseline", lambda: {
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 449.3,
        "count_scan_results": 37000,
        "count_analyze_results": 2700,
        "count_alerts": 50,
        "active_signals": 5500,
        "with_eligibility": 2700,
    })
    monkeypatch.setattr(notify_admin_cron, "_alerts_in_window",
                        lambda _: [
                            {"ticker": "TSLA", "alert_type": "enter",
                             "sent_at": "2026-05-22T08:20:00+00:00"},
                            {"ticker": "GOOGL", "alert_type": "enter",
                             "sent_at": "2026-05-22T08:21:00+00:00"},
                            {"ticker": "005930.KS", "alert_type": "disclosure",
                             "sent_at": "2026-05-22T08:22:00+00:00"},
                        ])
    yield


def _captured_message() -> str:
    """Read the message the dry-run mock captured (log INFO)."""
    raise NotImplementedError  # placeholder — replaced per-test below


# ─────────────────────────────────────────────────────────────────────
# start command
# ─────────────────────────────────────────────────────────────────────

def test_start_writes_baseline_file(fake_baseline_path):
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        rc = notify_admin_cron.cmd_start(dry_run=False)
    assert rc == 0
    assert fake_baseline_path.exists()
    data = json.loads(fake_baseline_path.read_text(encoding="utf-8"))
    assert data["db_size_mb"] == 449.3
    assert data["captured_at"] == "2026-05-22T08:00:00+00:00"
    # Telegram message sent to admins.
    assert mock_post.call_count == 1
    sent_text = mock_post.call_args[0][0]
    assert "Daily-scan 시작" in sent_text
    assert "449.3 MB" in sent_text
    assert "활성 신호" in sent_text


def test_start_includes_run_url_when_env_present(fake_baseline_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "jungrok5/thesauros")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        notify_admin_cron.cmd_start(dry_run=False)
    sent_text = mock_post.call_args[0][0]
    assert "github.com/jungrok5/thesauros/actions/runs/12345" in sent_text


def test_start_works_without_run_env(fake_baseline_path, monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        rc = notify_admin_cron.cmd_start(dry_run=False)
    assert rc == 0
    sent_text = mock_post.call_args[0][0]
    # Body still has the essentials — just no link.
    assert "Daily-scan 시작" in sent_text


# ─────────────────────────────────────────────────────────────────────
# end command — status mapping
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected_icon,expected_label", [
    ("success",   "✅", "완료"),
    ("failure",   "❌", "실패"),
    ("cancelled", "🟡", "취소됨"),
])
def test_end_status_maps_to_correct_header(
    fake_baseline_path, status, expected_icon, expected_label,
):
    # Pre-populate baseline as if `start` had run.
    fake_baseline_path.write_text(json.dumps({
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 440.0,
        "count_scan_results": 36000,
        "count_analyze_results": 2700,
        "count_alerts": 47,
        "active_signals": 5500,
        "with_eligibility": 2700,
    }), encoding="utf-8")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        rc = notify_admin_cron.cmd_end(status=status, dry_run=False)
    assert rc == 0
    sent_text = mock_post.call_args[0][0]
    first_line = sent_text.splitlines()[0]
    assert expected_icon in first_line, first_line
    assert expected_label in first_line, first_line


def test_end_unknown_status_uses_neutral_header(fake_baseline_path):
    fake_baseline_path.write_text(json.dumps({
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 440.0,
        "count_scan_results": 36000,
        "count_analyze_results": 2700,
        "active_signals": 5500,
        "with_eligibility": 2700,
    }), encoding="utf-8")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        notify_admin_cron.cmd_end(status="weird-status", dry_run=False)
    sent_text = mock_post.call_args[0][0]
    assert "🔵" in sent_text  # neutral fallback
    assert "weird-status" in sent_text


# ─────────────────────────────────────────────────────────────────────
# end command — diff math + content
# ─────────────────────────────────────────────────────────────────────

def test_end_renders_db_size_delta(fake_baseline_path):
    fake_baseline_path.write_text(json.dumps({
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 442.0,
        "count_scan_results": 32000,
        "count_analyze_results": 2700,
        "active_signals": 5000,
        "with_eligibility": 2700,
    }), encoding="utf-8")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        notify_admin_cron.cmd_end(status="success", dry_run=False)
    sent_text = mock_post.call_args[0][0]
    # _capture_baseline (now) is 449.3MB; baseline was 442.0 → +7.3MB
    assert "+7.3MB" in sent_text or "+7.3 MB" in sent_text or "7.3MB" in sent_text


def test_end_lists_alert_counts_by_type(fake_baseline_path):
    fake_baseline_path.write_text(json.dumps({
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 449.3,
        "count_scan_results": 37000,
        "count_analyze_results": 2700,
        "active_signals": 5500,
        "with_eligibility": 2700,
    }), encoding="utf-8")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        notify_admin_cron.cmd_end(status="success", dry_run=False)
    sent_text = mock_post.call_args[0][0]
    # _alerts_in_window mock returns 2 enter + 1 disclosure.
    assert "새 alert: 3건" in sent_text
    assert "enter=2" in sent_text
    assert "disclosure=1" in sent_text


def test_end_reports_eligibility_coverage(fake_baseline_path):
    fake_baseline_path.write_text(json.dumps({
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 449.3,
        "count_scan_results": 37000,
        "count_analyze_results": 2700,
        "active_signals": 5500,
        "with_eligibility": 2700,
    }), encoding="utf-8")
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        notify_admin_cron.cmd_end(status="success", dry_run=False)
    sent_text = mock_post.call_args[0][0]
    assert "eligibility 적재" in sent_text
    assert "2,700/2,700" in sent_text or "100%" in sent_text


def test_end_survives_missing_baseline(fake_baseline_path):
    """If start failed to write its snapshot, end must still send a
    sensible message — just without the diff lines."""
    # No file created → baseline missing.
    assert not fake_baseline_path.exists()
    with patch.object(notify_admin_cron, "_post_to_admins", return_value=1) as mock_post:
        rc = notify_admin_cron.cmd_end(status="success", dry_run=False)
    assert rc == 0
    sent_text = mock_post.call_args[0][0]
    # Header + DB size still present; no "소요" / "새 alert" lines.
    assert "Daily-scan 완료" in sent_text
    assert "DB:" in sent_text


# ─────────────────────────────────────────────────────────────────────
# Admin discovery — single source of truth
# ─────────────────────────────────────────────────────────────────────

def test_post_to_admins_uses_cron_health_helpers():
    """Both `cron_health.py` (the stale-data alerter) and this module
    must pull from the same admin list — otherwise adding a new admin
    in the DB would require updating both places."""
    with patch.object(notify_admin_cron, "admin_chat_ids", return_value=["111", "222"]) as mock_ids:
        with patch.object(notify_admin_cron, "send_telegram", return_value=True) as mock_send:
            notify_admin_cron._post_to_admins("hello", dry_run=False)
    assert mock_ids.call_count == 1
    assert mock_send.call_count == 2  # one per admin


def test_start_aborts_when_db_above_hard_ceiling(fake_baseline_path, monkeypatch):
    """DB 95% 이상이면 start ping 이 abort 메시지 발사 후 exit(2). 회고
    #52 — Supabase read-only 진입 방지의 외측 가드. retention.py 의
    90% trigger 와 별개 — retention 이 못 따라잡는 ingest 폭주 시 외측
    중단."""
    # 95% = 475MB. _capture_baseline 가 fake 데이터 returnning 하므로
    # 그 fake 의 db_size_mb 를 96% 로 override.
    monkeypatch.setattr(notify_admin_cron, "_capture_baseline", lambda: {
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 480.0,   # 96%
        "count_scan_results": 37000,
        "count_analyze_results": 2700,
        "active_signals": 5500,
        "with_eligibility": 2700,
    })
    posted: list[str] = []
    monkeypatch.setattr(notify_admin_cron, "_post_to_admins",
                        lambda text, dr: posted.append(text) or 1)
    rc = notify_admin_cron.cmd_start(dry_run=False)
    assert rc == 2, "exit code must be non-zero so workflow step fails"
    assert any("HARD ceiling" in t for t in posted)
    assert any("96.0%" in t for t in posted)


def test_start_warns_when_db_in_soft_band(fake_baseline_path, monkeypatch):
    """90-95% 구간은 abort 안 함 — 경고만 prepend. cron 진행."""
    monkeypatch.setattr(notify_admin_cron, "_capture_baseline", lambda: {
        "captured_at": "2026-05-22T08:00:00+00:00",
        "db_size_mb": 460.0,   # 92%
        "count_scan_results": 37000,
        "count_analyze_results": 2700,
        "active_signals": 5500,
        "with_eligibility": 2700,
    })
    posted: list[str] = []
    monkeypatch.setattr(notify_admin_cron, "_post_to_admins",
                        lambda text, dr: posted.append(text) or 1)
    rc = notify_admin_cron.cmd_start(dry_run=False)
    assert rc == 0
    assert any("WARNING" in t for t in posted)


def test_start_silent_when_db_under_soft_band(fake_baseline_path, monkeypatch):
    """SOFT 미만이면 일반 시작 메시지 — WARNING / abort prefix 없음."""
    # default fake_baseline 의 db_size_mb 는 449.3 (89.86%) — SOFT 미만.
    posted: list[str] = []
    monkeypatch.setattr(notify_admin_cron, "_post_to_admins",
                        lambda text, dr: posted.append(text) or 1)
    rc = notify_admin_cron.cmd_start(dry_run=False)
    assert rc == 0
    assert all("HARD ceiling" not in t for t in posted)
    assert all("WARNING" not in t for t in posted)


def test_post_to_admins_dry_run_does_not_call_telegram():
    with patch.object(notify_admin_cron, "admin_chat_ids", return_value=["111"]):
        with patch.object(notify_admin_cron, "send_telegram") as mock_send:
            notify_admin_cron._post_to_admins("hello", dry_run=True)
    assert mock_send.call_count == 0
