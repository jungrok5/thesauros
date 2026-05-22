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

# Destructive 토큰 정규식 (회고 #44/#45 — 우회 가능성 확장 차단).
# 주석 stripped 된 SQL 에서 anywhere 매치 — 한 줄 BEGIN; DROP TABLE foo;
# 또는 multi-line DROP\nTABLE 둘 다 잡힘.
#
# 검사 대상:
#   DROP TABLE              테이블 삭제
#   DROP SCHEMA             스키마 통째 삭제
#   DROP MATERIALIZED VIEW  마뷰 삭제 (데이터 손실)
#   TRUNCATE                일괄 삭제
#   DELETE FROM ... 일 때 WHERE 절이 없거나 trivially true (`WHERE true`,
#                  `WHERE 1=1`) — 전체 행 삭제 사실상 TRUNCATE
#
# DROP INDEX / DROP COLUMN 은 행 손실 X (IF EXISTS 면 idempotent) — 미차단.
_DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE",
     re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE | re.DOTALL)),
    ("DROP SCHEMA",
     re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE | re.DOTALL)),
    ("DROP MATERIALIZED VIEW",
     re.compile(r"\bDROP\s+MATERIALIZED\s+VIEW\b", re.IGNORECASE | re.DOTALL)),
    ("TRUNCATE",
     re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    # DELETE FROM 은 합법적 사용 (retention 정책의 DELETE 같은 것) 가능
    # 하지만 migrations 폴더 안에서는 DELETE FROM 자체가 위험. 명시 등록
    # (045) 만 허용.
    ("DELETE FROM",
     re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE | re.DOTALL)),
]

# 정책 예외 — 새 destructive 가 정말 필요하면 여기 추가하고 PR 리뷰에서
# 명시적 승인. 보통 비어있어야 정상.
#
# 045_remove_us_universe.sql:
#   - DELETE FROM bars / analyze_results / scan_results / fundamentals /
#     disclosures WHERE ticker IN (...) — US universe 5000+ 종목 영구 삭제.
#   - 회고 #8: 적용 전 Supabase dashboard Database → Backups 에서
#     manual backup 권장. PITR (Pro: 7일) 으로 24h 내엔 복구 가능.
#   - 영구 destructive 임이 분명하므로 ALLOWED 명시 — replay guard 의
#     DELETE FROM 검사 (#45) 가 추가되면 이 migration 만 통과시킴.
ALLOWED_DESTRUCTIVE: set[str] = {
    # P_US — 의도된 영구 destructive. 045 SQL 헤더에 backup 절차 명시.
    "045_remove_us_universe.sql",
    # 020 — 한 번 적용된 investor_flow 30일 retention DELETE. 재실행
    # 시 idempotent (WHERE day < CURRENT_DATE - 30) — 그날 기준 30일
    # 이상 행 삭제는 retention.py 의 일상 동작.
    "020_drop_bars_date_index_shrink_investor.sql",
    # 026 — search_history trim_search_history() trigger 내부 DELETE.
    # 매 INSERT 시 자동 trim 의도. trigger 정의일 뿐 migration replay 시
    # 데이터 손실 X.
    "026_search_history_and_feedback.sql",
}


def _strip_sql_comments(src: str) -> str:
    """Remove `-- ...` and /* ... */ comments before scanning. 주석 안에
    DROP TABLE 이 자유롭게 쓰여도 OK (historical 설명용).
    """
    # /* ... */ multi-line comments
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    # -- line comments
    src = re.sub(r"--[^\n]*", "", src)
    return src


def _scan(path: Path) -> list[str]:
    """Return list of destructive token names found (주석 stripped)."""
    raw = path.read_text(encoding="utf-8")
    stripped = _strip_sql_comments(raw)
    return [name for name, pat in _DESTRUCTIVE_PATTERNS if pat.search(stripped)]


def test_no_destructive_in_migrations():
    """모든 migrations/*.sql 에서 (주석 제외) DROP TABLE / DROP SCHEMA /
    DROP MATERIALIZED VIEW / TRUNCATE / DELETE FROM 발견 시 fail.

    이미 적용된 destructive 는 ALLOWED_DESTRUCTIVE 에 명시. 새 destructive
    가 정말 필요하면 ops script 로 분리 + PR review.
    """
    if not _MIGRATIONS.exists():
        return
    offenders: dict[str, list[str]] = {}
    for sql in sorted(_MIGRATIONS.glob("*.sql")):
        if sql.name in ALLOWED_DESTRUCTIVE:
            continue
        found = _scan(sql)
        if found:
            offenders[sql.name] = found
    assert not offenders, (
        "migrations 폴더에 destructive SQL 이 남아있음 — replay 시 prod "
        f"데이터 손실 위험. 영향: {dict(offenders)}. 조치: SQL 을 "
        "`SELECT 1` no-op 으로 비우거나 (이미 적용된 destructive) "
        "ALLOWED_DESTRUCTIVE 에 명시. 2026-05-22 themes 사고 참조."
    )


def test_regex_catches_adversarial_forms():
    """Bypass attempts the original DROP TABLE regex would miss.
    회고 #44/#45 — multi-line DROP\\nTABLE, BEGIN; DROP TABLE x;, etc."""
    fixtures = {
        "multi_line": "BEGIN;\n\nDROP\nTABLE foo;\n",
        "single_line": "BEGIN; DROP TABLE foo CASCADE; END;",
        "drop_schema": "DROP SCHEMA public CASCADE;",
        "drop_matview": "DROP MATERIALIZED VIEW theme_stats;",
        "truncate": "TRUNCATE TABLE bars RESTART IDENTITY;",
        "delete_from": "DELETE FROM bars WHERE bar_date < '2024-01-01';",
    }
    for case, sql in fixtures.items():
        found = [name for name, pat in _DESTRUCTIVE_PATTERNS if pat.search(sql)]
        assert found, f"adversarial fixture {case!r} not caught: {sql!r}"


def test_safe_sql_is_not_caught():
    """건강한 SQL — false positive 차단."""
    safe = [
        "CREATE TABLE foo (id INT);",
        "ALTER TABLE foo ADD COLUMN bar INT;",
        "DROP INDEX IF EXISTS idx_old;",
        "DROP COLUMN IF EXISTS old_col;",
        "SELECT 1;",
        "-- DROP TABLE in comment shouldn't fire",
        "/* TRUNCATE in block comment */",
    ]
    for sql in safe:
        stripped = _strip_sql_comments(sql)
        found = [name for name, pat in _DESTRUCTIVE_PATTERNS if pat.search(stripped)]
        assert not found, f"safe SQL falsely flagged: {sql!r} → {found}"


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
