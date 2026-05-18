-- 016_drop_bars_desc_index.sql — reclaim ~44MB.
--
-- `idx_bars_daily_ticker_date_desc` was created in migration 013 to
-- speed up "latest N bars per ticker" queries (quote / chart). Postgres
-- can serve those from `bars_daily_pkey` (ticker, bar_date) via a
-- reverse index scan, at a small CPU cost. With the Supabase free-tier
-- 500MB cap pressing, the storage win outweighs the per-query overhead
-- (these queries hit a handful of rows and are not on a hot path).
--
-- If the chart/quote latency regresses noticeably, re-create with:
--   CREATE INDEX idx_bars_daily_ticker_date_desc
--     ON bars_daily (ticker, bar_date DESC);

DROP INDEX IF EXISTS idx_bars_daily_ticker_date_desc;
