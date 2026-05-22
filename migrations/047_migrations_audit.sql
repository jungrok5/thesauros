-- 047 — migrations_audit: immutable append-only log of migration apply events.
--
-- 회고 #47: _migrations 가 외부 작업 (Supabase dashboard / CLI db push)
-- 으로 reset 가능 — 그 결과 historical destructive (022) 가 재실행돼
-- 2026-05-22 새벽 themes 가 다시 drop 됨. _migrations 자체가 source of
-- truth 가 아니라는 게 문제.
--
-- migrations_audit 는 INSERT-only — UPDATE/DELETE 정책 X. _migrations 이
-- 어떻게 manipulate 돼도 audit 에는 매 apply 이벤트가 영구 기록. 다음
-- replay 시 migrate.py 가 audit 와 _migrations 의 diff 발견해 admin alert.

CREATE TABLE IF NOT EXISTS migrations_audit (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- runner (인간/CI) 식별 — env 에서 채워짐. NULL 도 OK (dashboard 등
    -- 외부 실행 시 모를 수 있음).
    runner      TEXT,
    -- "apply" / "replay" / "noop" — 단순 apply 인지 재실행인지 구분.
    -- replay = 같은 이름이 이전에 이미 등록된 적 있음 (rare, 사고 신호).
    event_type  TEXT NOT NULL DEFAULT 'apply'
);

CREATE INDEX IF NOT EXISTS idx_migrations_audit_name
    ON migrations_audit (name);

-- RLS — service-role 만 INSERT 가능. anon/authenticated 는 read X.
-- 일반 사용자가 migration history 못 보게.
ALTER TABLE migrations_audit ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE migrations_audit IS
  'Append-only audit log of migration apply events. _migrations 가 reset '
  '되어도 여기는 잔존 — replay detection 의 source of truth.';
