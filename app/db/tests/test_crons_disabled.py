"""Static guard: all scheduled crons stay paused (2026-07-08).

Telegram/Vercel/GitHub-Actions cron automation was paused per request.
The pause is expressed as config — commented-out `schedule:` blocks in
every workflow and a `crons`-less vercel.json. These tests pin that
state so a future edit can't silently re-arm the schedule. If a cron is
intentionally re-enabled later, update these tests in the same commit.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _active_lines(text: str) -> list[str]:
    """Non-comment YAML lines (strip full-line `#` comments)."""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_no_workflow_has_active_cron_schedule():
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        for ln in _active_lines(wf.read_text(encoding="utf-8")):
            if re.match(r"\s*-\s*cron:", ln):
                offenders.append(f"{wf.name}: {ln.strip()}")
    assert not offenders, (
        "Scheduled cron(s) are active but should stay paused:\n"
        + "\n".join(offenders)
    )


def test_vercel_json_has_no_crons():
    vercel = _ROOT / "vercel.json"
    cfg = json.loads(vercel.read_text(encoding="utf-8"))
    assert "crons" not in cfg, (
        "vercel.json defines `crons` but Vercel cron should stay paused"
    )
