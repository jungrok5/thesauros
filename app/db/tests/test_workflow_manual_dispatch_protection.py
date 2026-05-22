"""Static-analysis tests for weekly-scan.yml manual-dispatch protection.

Background — 책 정신 (2부 3장): 매매 결정 알림은 주봉 종가 후 1회.
weekly-scan.yml 이 매주 금요일 17 KST 에 자동 실행되지만 admin 이
workflow_dispatch 로 수동 트리거 시 비-금요일에도 alert 가 발사돼
사용자가 "왜 화요일에 매수 alert?" 혼란 가능. 보호 장치:

  - workflow_dispatch 에 `send_alerts: boolean default false` input.
  - telegram_worker step 이 inputs.send_alerts=false 면 --dry-run 으로
    실행 (log 만, 발송 X).
  - Scheduled trigger (Vercel Cron) 시엔 input 없으므로 진짜 발송.

These tests pin those invariants so a future YAML edit can't silently
remove the guard.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "weekly-scan.yml"


def _read_yml() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_workflow_dispatch_has_send_alerts_input():
    """The workflow_dispatch trigger MUST expose a send_alerts input —
    that's the only knob admin uses to opt into actual alert sending
    on manual runs."""
    src = _read_yml()
    assert "workflow_dispatch:" in src, "workflow_dispatch trigger missing"
    assert "send_alerts:" in src, "send_alerts input missing"
    assert "default: false" in src, (
        "send_alerts must default to false — book-spirit safety"
    )


def test_telegram_step_branches_on_input():
    """The telegram_worker invocation must check both
    github.event_name == 'workflow_dispatch' AND inputs.send_alerts so
    that scheduled cron runs still send alerts but manual ones default
    to dry-run."""
    src = _read_yml()
    # Look for the two conditions that gate dry-run mode.
    assert "github.event_name" in src and "workflow_dispatch" in src
    assert "inputs.send_alerts" in src
    # The dry-run command must actually be issued.
    assert "--dry-run" in src
    # And the python module must still be called either way.
    assert "telegram_worker" in src


def test_telegram_step_in_weekly_scan_only():
    """Daily-data.yml MUST NOT call telegram_worker — book-spirit
    decision alerts belong to weekly-scan only. (Disclosure alerts in
    daily-data are a different module: notify_disclosure_alerts.)"""
    daily = (_ROOT / ".github" / "workflows" / "daily-data.yml").read_text(encoding="utf-8")
    # `telegram_worker` (signal alerts) must NOT appear in daily.
    assert "app.db.telegram_worker" not in daily, (
        "telegram_worker leaked into daily-data — decision alerts must "
        "fire on weekly-scan only (책 정신)"
    )
    # And disclosure alerts (separate module) SHOULD be in daily.
    assert "notify_disclosure_alerts" in daily
