-- 025_drop_bars_daily.sql — NO-OP (historical placeholder).
--
-- 원래 의도 (2026-05-19, weekly pivot 직후): DROP TABLE IF EXISTS
-- bars_daily CASCADE. 022 와 동일한 패턴으로 no-op 화 — migration
-- replay 시 우연한 데이터 손실 방지.
--
-- 영구 보호 정책 — 모든 DROP TABLE / TRUNCATE 는 적용 후 no-op 화.
-- test_no_destructive_replay.py 가 회귀 가드.

SELECT 1;   -- explicit no-op
