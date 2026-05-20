-- 028 — search_history dedupe per (user_id, query)
--
-- 사용자 요청 (2026-05-20): \"동일한 건 추가하지 마\". 같은 query 를
-- 다시 검색하면 새 row 추가 대신 기존 row 의 created_at 만 갱신해서
-- 가장 최근 위치로. UNIQUE 제약 + ON CONFLICT DO UPDATE 패턴.
--
-- 부수효과: 30-trim 트리거는 AFTER INSERT 만 fire — 중복 query 는
-- INSERT 가 UPDATE 로 변환되므로 트리거 안 돈다 (정상 — 행 수 안 늘어남).

CREATE UNIQUE INDEX IF NOT EXISTS uniq_search_history_user_query
  ON search_history (user_id, query);
