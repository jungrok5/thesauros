-- 024_drop_trade_log.sql — NO-OP (historical placeholder).
--
-- 원래 의도 (2026-05-19): DROP TABLE IF EXISTS trade_log CASCADE.
-- 022 와 동일한 패턴으로 no-op 화 — migration replay 시 우연한 데이터
-- 손실 방지. trade_log 자체는 의도적으로 영구 drop 됐고 (search-only
-- pivot 후 소비자 0) 새로 만들 계획 없음. 그래도 누가 같은 이름의
-- 새 테이블 만들고 024 가 재실행되면 destroyed.
--
-- 영구 보호 정책 — 모든 DROP TABLE / TRUNCATE 는 적용 후 no-op 화.
-- test_no_destructive_replay.py 가 회귀 가드.

SELECT 1;   -- explicit no-op
