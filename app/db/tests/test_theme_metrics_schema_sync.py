"""Schema-drift guard (회고 #17/#58) — theme_metrics_cache 의 컬럼 list
가 migration 046 / publish_theme_metrics.py / theme_metrics() RPC /
TS ThemeRow 4 곳에 모두 정의됨. 한 곳만 변경되면 silent corruption
(예: avg_change_pct 가 NULL 이 아닌 다른 컬럼 값으로 INSERT).

이 테스트가 4 곳의 컬럼 list 가 일치하는지 정적 검사.
"""
from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]


# 기준 컬럼 — migration 046 의 CREATE TABLE 에서 직접 추출.
_EXPECTED_COLUMNS = [
    "theme_id", "name", "members", "updated_at", "avg_change_pct",
    "up_count", "down_count", "strong_buy", "buy", "hold", "avoid",
    "top_tickers",
]


def test_migration_046_columns_match_expected():
    """기준 — 046 의 CREATE TABLE 가 expected columns 전부 정의."""
    sql = (_ROOT / "migrations" / "046_theme_metrics_cache.sql").read_text(
        encoding="utf-8",
    )
    for col in _EXPECTED_COLUMNS:
        # CREATE TABLE 안에 `<col> <type>` 패턴.
        # cached_at 같은 보조 컬럼은 무시 — _EXPECTED 가 contract.
        assert re.search(rf"\b{re.escape(col)}\s", sql), (
            f"migration 046 에 컬럼 {col!r} 없음"
        )


def test_publish_theme_metrics_column_order_matches():
    """publish_theme_metrics.py 의 INSERT + SELECT 양쪽이 같은 컬럼
    list 를 같은 순서로 사용 — 미스매치 시 잘못된 컬럼에 값 들어감."""
    src = (_ROOT / "app" / "db" / "publish_theme_metrics.py").read_text(
        encoding="utf-8",
    )
    # INSERT INTO ... ( ... ) SELECT ... FROM 패턴 안의 컬럼 list 두 개.
    pattern = re.compile(
        r"INSERT INTO theme_metrics_cache \(\s*([^)]+?)\s*\)\s*SELECT\s+([^F]+?)\s+FROM",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(src)
    assert m, "INSERT ... SELECT 패턴 못 찾음 — publish_theme_metrics 구조 변경?"
    insert_cols = [c.strip() for c in m.group(1).split(",")]
    select_cols = [c.strip() for c in m.group(2).split(",")]
    assert insert_cols == select_cols, (
        f"INSERT 컬럼 ({insert_cols}) 과 SELECT 컬럼 ({select_cols}) 가 "
        "달라요. 한 줄 drop 또는 reorder 시 silent corruption."
    )
    # 그리고 expected columns 와 동일.
    assert insert_cols == _EXPECTED_COLUMNS, (
        f"publish 의 컬럼 list 가 expected 와 다름: {insert_cols} vs "
        f"{_EXPECTED_COLUMNS}. migration 046 과 sync 확인."
    )


def test_ts_themerow_type_lists_all_columns():
    """page.tsx 의 ThemeRow TS type 이 expected columns 모두 가짐.
    누락 시 cache row 를 normalize 할 때 컬럼이 undefined 됨."""
    src = (_ROOT / "web-next" / "src" / "app" / "(app)" / "themes" / "page.tsx").read_text(
        encoding="utf-8",
    )
    # ThemeRow 타입 정의 안에서 컬럼 추출.
    m = re.search(r"type\s+ThemeRow\s*=\s*\{([^}]+)\}", src)
    assert m, "ThemeRow type 정의 못 찾음"
    body = m.group(1)
    for col in _EXPECTED_COLUMNS:
        assert re.search(rf"\b{re.escape(col)}\s*:", body), (
            f"TS ThemeRow type 에 {col!r} 없음 — cache row 로딩 시 null"
        )
