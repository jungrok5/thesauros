-- 015_drop_news.sql — NO-OP (historical placeholder).
-- 원래 의도: DROP TABLE IF EXISTS news CASCADE. 영구 보호 정책으로 no-op 화.
-- 정책 + 회귀 가드: app/db/tests/test_no_destructive_replay.py

SELECT 1;
