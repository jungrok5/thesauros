-- 038 — bars 인덱스 다이어트 + DB 용량 긴급 fix
--
-- 사용자 확인 (2026-05-20): DB 497 MB / 500 MB (104%) — 한도 초과.
-- 원인: migration 034 의 idx_bars_granularity_date INCLUDE (ticker,
-- close, volume) covering 인덱스가 41 MB — bars PK (47 MB) 거의
-- 같은 크기. 786K rows × covering columns = 큰 용량.
--
-- 수정: INCLUDE 절 제거. (granularity, bar_date) 만 인덱싱.
-- 단점: volume_surges RPC 가 인덱스 lookup 후 heap 한번 더 fetch.
-- 그러나 행 수가 (이번주 + 직전 8주 = 9 rows × 2,700 tickers) 작아서
-- heap access 추가 cost 미미.

DROP INDEX IF EXISTS idx_bars_granularity_date;

CREATE INDEX idx_bars_granularity_date
    ON bars (granularity, bar_date DESC);
-- 위는 INCLUDE 없는 일반 btree — covering 못 함 but 인덱스 크기 ~10MB
