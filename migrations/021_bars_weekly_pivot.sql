-- 021_bars_weekly_pivot.sql — drop daily storage, create unified bars
-- table holding weekly + monthly bars only.
--
-- Rationale: book strategy is swing trading; primary signals are 월봉
-- 240MA + 월봉/주봉 10MA. Daily bars added storage cost without analysis
-- value. Plus yfinance is blocked from cloud runners — Naver only exposes
-- weekly + monthly for US, so daily was always going to be KR-only.
--
-- This migration:
--   1. DROP TABLE bars_daily — the data is regeneratable from FDR (KR)
--      and Naver (US). No need to migrate rows.
--   2. CREATE TABLE bars with granularity column.
--   3. Same RLS pattern (public SELECT, FORCE RLS on writes via service-role).
--
-- After this migration the ingest cron must repopulate bars within 1 run.

BEGIN;

DROP TABLE IF EXISTS bars_daily;

CREATE TABLE bars (
    ticker      VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    granularity CHAR(1)     NOT NULL CHECK (granularity IN ('W','M')),
    -- Week-ending Friday for 'W', month-ending last business day for 'M'.
    bar_date    DATE        NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    adj_close   NUMERIC,
    volume      BIGINT,
    PRIMARY KEY (ticker, granularity, bar_date)
);

-- Retention queries hit (granularity, bar_date); analyzer reads
-- (ticker, granularity) — both covered by the PK index because PK
-- is (ticker, granularity, bar_date). No separate index needed.

ALTER TABLE bars ENABLE ROW LEVEL SECURITY;
ALTER TABLE bars FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_bars_read ON bars;
CREATE POLICY p_bars_read ON bars FOR SELECT TO anon, authenticated USING (true);

COMMIT;
