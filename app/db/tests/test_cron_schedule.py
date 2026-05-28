"""Pin GH-native `on: schedule:` on the two production cron workflows.

Background — 2026-05-28: Vercel cron (configured via vercel.json crons
array) was confirmed NOT to fire on the Hobby tier. Last 48h Vercel
function logs showed zero `/api/cron/daily-data` invocations from the
scheduler. Every successful Daily Data Refresh run was a manual
`workflow_dispatch`. As a fix, both workflows added a native GH
`on: schedule:` trigger (primary) while keeping the Vercel chain as a
fallback. Since the repo is PUBLIC, GH Actions runs are free.

These tests pin the schedule blocks so they can't silently get dropped
(eg. someone "cleaning up" the trigger list) and re-introduce the
"cron never fires" failure mode.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_daily_data_has_schedule_trigger():
    src = _read("daily-data.yml")
    assert "schedule:" in src, "daily-data.yml lost `on: schedule:` block"
    # KR market: 17:00 KST = 08:00 UTC, weekdays only.
    assert '- cron: "0 8 * * 1-5"' in src, (
        "daily-data.yml schedule cron must be '0 8 * * 1-5' "
        "(매일 17:00 KST 평일만)"
    )


def test_weekly_scan_has_schedule_trigger():
    src = _read("weekly-scan.yml")
    assert "schedule:" in src, "weekly-scan.yml lost `on: schedule:` block"
    # Friday only, 17:30 KST = 08:30 UTC. 책 정신: 주봉 종가 후 1회.
    assert '- cron: "30 8 * * 5"' in src, (
        "weekly-scan.yml schedule cron must be '30 8 * * 5' "
        "(금요일 17:30 KST 1회)"
    )


def test_workflow_dispatch_kept_alongside_schedule():
    """Manual `workflow_dispatch` must remain for ad-hoc reruns +
    Vercel cron fallback. Removing it would make the workflow
    unreplayable when a scheduled run silently fails."""
    for fname in ("daily-data.yml", "weekly-scan.yml"):
        src = _read(fname)
        assert "workflow_dispatch:" in src, (
            f"{fname}: workflow_dispatch trigger is required as a "
            f"fallback channel — do not remove it when adding schedule:."
        )
