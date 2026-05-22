"""Tests for migrate.py replay-detection guard (회고 #47).

Background: 2026-05-22 새벽 _migrations 가 어딘가에서 reset 되어
022_drop_themes 가 재실행됨 → 부활한 themes 데이터 다시 drop. migrate.py
자체는 그게 "정상 apply" 로 보였음 (_migrations 가 비었으니).

영구 보호 — migrations_audit 라는 append-only 테이블로 모든 apply
이벤트 기록. migrate up 이 새 migration 적용 직전에 audit 를 조회 —
"이미 기록 있음" 이면 = _migrations reset 발생 신호 → ABORT (admin 이
명시 의도면 MIGRATE_ALLOW_REPLAY=1 로 override).

이 테스트는 module-level functions 의 단위 테스트 — DB 없이 mock 으로.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import migrate


def _stub_cur_with_audit_seen(seen_names: set[str]):
    """Return a MagicMock cursor whose `_audit_seen` returns True only
    for names in seen_names."""
    cur = MagicMock()
    def fetchone_factory():
        # _audit_seen executes "SELECT EXISTS (...)" then fetchone.
        # We need to inspect the last execute call.
        last_sql = cur.execute.call_args.args[0] if cur.execute.call_args else ""
        last_params = (
            cur.execute.call_args.args[1]
            if cur.execute.call_args and len(cur.execute.call_args.args) > 1
            else ()
        )
        if "EXISTS" in last_sql.upper() and last_params:
            name = last_params[0]
            return (name in seen_names,)
        return (None,)
    cur.fetchone.side_effect = fetchone_factory
    return cur


def test_audit_seen_returns_true_for_known_name():
    cur = _stub_cur_with_audit_seen({"022_drop_themes.sql"})
    assert migrate._audit_seen(cur, "022_drop_themes.sql") is True
    assert migrate._audit_seen(cur, "999_new.sql") is False


def test_audit_record_inserts_with_runner_from_env(monkeypatch):
    """audit_record 는 GITHUB_ACTOR / USER / USERNAME 중 가장 먼저
    정의된 것을 runner 컬럼에 기록."""
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    cur = MagicMock()
    migrate._audit_record(cur, "048_test.sql", "abc123")
    args = cur.execute.call_args
    assert "INSERT INTO migrations_audit" in args.args[0]
    assert args.args[1] == ("048_test.sql", "abc123", "ci-bot", "apply")


def test_audit_record_falls_back_to_unknown(monkeypatch):
    """env 없으면 'unknown' — 적어도 무엇은 채워짐 (NULL 회피)."""
    monkeypatch.delenv("GITHUB_ACTOR", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    cur = MagicMock()
    migrate._audit_record(cur, "x.sql", "h")
    runner = cur.execute.call_args.args[1][2]
    assert runner == "unknown"


def test_audit_record_marks_replay_event_type():
    """event_type='replay' 로 호출되면 그대로 INSERT — 일반 'apply' 와
    구분되어 admin 이 audit 조회 시 사고 신호 식별."""
    cur = MagicMock()
    migrate._audit_record(cur, "022_drop_themes.sql", "h", "replay")
    assert cur.execute.call_args.args[1][3] == "replay"
