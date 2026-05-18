-- 020_drop_bars_date_index_shrink_investor.sql
--
-- 1) DROP `idx_bars_daily_date` (10 MB). Single-column index on
--    bar_date is only useful for "scan all tickers on a given date"
--    style queries — we have zero such queries in the app today.
--    All hot reads use (ticker, bar_date) which is served by the PK.
--
-- 2) Drop investor_flow rows older than 30 days. The UI only shows
--    last 5 days; the previous 90-day retention was over-conservative.
--    Frees ~20 MB on the current dataset.

DROP INDEX IF EXISTS idx_bars_daily_date;

DELETE FROM investor_flow
 WHERE day < CURRENT_DATE - INTERVAL '30 days';
