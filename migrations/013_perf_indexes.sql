-- 013_perf_indexes.sql — composite index for "latest N bars per ticker"
--
-- /api/quote/[ticker] and BookChart both do:
--   SELECT ... FROM bars_daily WHERE ticker = $1 ORDER BY bar_date DESC LIMIT N
-- The existing `idx_bars_daily_date (bar_date DESC)` (migration 003) is
-- useful for date-range scans across all tickers but NOT for the per-
-- ticker latest-bars pattern (Postgres would have to scan all ticker
-- entries for that day). The PK is (ticker, bar_date) which helps with
-- range scans but ORDER BY DESC LIMIT on the per-ticker subset works
-- best with an explicit DESC composite.

CREATE INDEX IF NOT EXISTS idx_bars_daily_ticker_date_desc
    ON bars_daily (ticker, bar_date DESC);
