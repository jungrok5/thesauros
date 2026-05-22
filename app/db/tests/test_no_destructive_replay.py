"""Permanent protection — migrations 폴더 안에 DROP TABLE / TRUNCATE 가
남아있으면 fail.

배경 (2026-05-22 사고): _migrations tracker 가 외부 작업 (Supabase
dashboard, CLI db push 등) 으로 reset/replay 되면 historical destructive
migration 들이 다시 실행돼 prod 의 살아있는 데이터를 drop 한다. 실제
사례:

  - 2026-05-19  022_drop_themes.sql 적용 → themes/theme_daily/theme_members DROP
  - 2026-05-20  041_themes_restore.sql 로 themes/theme_members 부활 (사용자가
                 외부 SQL 로 직접 적용, _migrations 트래커엔 미등록)
  - 2026-05-22  새벽 07:18 _migrations replay 발생 → 022 가 다시 실행되어
                 부활된 themes 다시 DROP. 사용자 데이터 손실 + /themes 페이지
                 빈 응답.

영구 방어 정책:
  1. 이미 적용된 destructive migration 들은 SQL 을 `SELECT 1` no-op 로
     비움 (014, 015, 022, 024, 025; 021 의 DROP 줄은 주석화).
  2. 이 테스트가 모든 migrations/*.sql 에서 DROP TABLE / TRUNCATE 토큰
     검출. 발견 시 fail → 새 destructive migration 추가 시 review 강제.

새 destructive migration 이 정말 필요하면:
  - 일회성 ops script (e.g. scripts/one_off_drop.py) 로 분리
  - 또는 명시적 archive 폴더 도입 + 이 테스트의 ALLOWED_DESTRUCTIVE 에 등록

DROP COLUMN / DROP INDEX 는 column/index 단위라 IF EXISTS 면 idempotent +
저위험 → 차단 안 함. 데이터 손실 가능한 DROP TABLE / TRUNCATE 만 차단.
"""
from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_MIGRATIONS = _ROOT / "migrations"

# 토큰 단위 정규식 — 주석 안에 있는 거 제외.
_DROP_TABLE_RE = re.compile(r"^\s*DROP\s+TABLE\b", re.IGNORECASE | re.MULTILINE)
_TRUNCATE_RE = re.compile(r"^\s*TRUNCATE\b", re.IGNORECASE | re.MULTILINE)

# 정책 예외 — 새 destructive 가 정말 필요하면 여기 추가하고 PR 리뷰에서
# 명시적 승인. 비어있는 게 정상 상태.
ALLOWED_DESTRUCTIVE: set[str] = set()


def _strip_sql_comments(src: str) -> str:
    """Remove `-- ...` and /* ... */ comments before scanning. 주석 안에
    DROP TABLE 이 자유롭게 쓰여도 OK (historical 설명용).
    """
    # /* ... */ multi-line comments
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    # -- line comments
    src = re.sub(r"--[^\n]*", "", src)
    return src


def _scan(path: Path) -> dict[str, bool]:
    raw = path.read_text(encoding="utf-8")
    stripped = _strip_sql_comments(raw)
    return {
        "drop_table": bool(_DROP_TABLE_RE.search(stripped)),
        "truncate": bool(_TRUNCATE_RE.search(stripped)),
    }


def test_no_drop_table_in_migrations():
    """모든 migrations/*.sql 에서 (주석 제외) DROP TABLE 발견되면 fail.

    DROP TABLE 은 가장 위험한 op — IF EXISTS 라도 테이블이 (부활 등으로)
    다시 생성된 상태면 prod 데이터 손실. _migrations replay 시 unintended
    실행 위험. 우회: SQL 을 `SELECT 1` no-op 로 비우거나 ALLOWED_DESTRUCTIVE
    에 명시.
    """
    if not _MIGRATIONS.exists():
        return
    offenders: list[str] = []
    for sql in sorted(_MIGRATIONS.glob("*.sql")):
        if sql.name in ALLOWED_DESTRUCTIVE:
            continue
        if _scan(sql)["drop_table"]:
            offenders.append(sql.name)
    assert not offenders, (
        "migrations 폴더에 DROP TABLE 이 남아있음 — replay 시 prod 데이터 "
        f"손실 위험. 영향: {sorted(offenders)}. 조치: SQL 을 `SELECT 1` "
        "no-op 으로 비우거나 (이미 적용된 destructive) ALLOWED_DESTRUCTIVE 에 "
        "명시 (의도적 destructive). 2026-05-22 themes 사고 참조."
    )


def test_no_truncate_in_migrations():
    """TRUNCATE 도 동일 — 데이터 wipe. migration 으로 하면 안 됨."""
    if not _MIGRATIONS.exists():
        return
    offenders: list[str] = []
    for sql in sorted(_MIGRATIONS.glob("*.sql")):
        if sql.name in ALLOWED_DESTRUCTIVE:
            continue
        if _scan(sql)["truncate"]:
            offenders.append(sql.name)
    assert not offenders, (
        "migrations 폴더에 TRUNCATE 가 있음. 데이터 wipe — replay 시 "
        f"prod 손실. 영향: {sorted(offenders)}. ops script 로 분리하거나 "
        "ALLOWED_DESTRUCTIVE 에 명시."
    )


def test_historical_drops_are_now_noop():
    """이미 적용된 5 개 historical DROP migrations 가 SELECT 1 (no-op) 로
    바뀌었는지 확인. 누가 실수로 SQL 을 복원하면 fail."""
    HISTORICAL = [
        "014_drop_chart_data.sql",
        "015_drop_news.sql",
        "022_drop_themes.sql",
        "024_drop_trade_log.sql",
        "025_drop_bars_daily.sql",
    ]
    for name in HISTORICAL:
        p = _MIGRATIONS / name
        if not p.exists():
            continue   # 누군가 정말 제거했다면 OK
        stripped = _strip_sql_comments(p.read_text(encoding="utf-8"))
        # SELECT 1 (with optional whitespace + semicolon) 만 존재.
        # 또는 완전히 빈 (모두 주석).
        non_comment = stripped.strip().rstrip(";").strip()
        assert non_comment.upper() in {"", "SELECT 1"}, (
            f"{name} should be no-op (`SELECT 1`) — got non-comment SQL: "
            f"{non_comment!r}. historical destructive 가 복원되면 prod 위험."
        )
