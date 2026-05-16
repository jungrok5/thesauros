-- 003_indexes.sql — indexes for hot query paths

-- Ticker search (fuzzy autocomplete by name)
CREATE INDEX IF NOT EXISTS idx_tickers_name_trgm
    ON tickers USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_tickers_market
    ON tickers (market) WHERE is_active = true;

-- Watchlist by user
CREATE INDEX IF NOT EXISTS idx_watchlist_user
    ON watchlist (user_id, created_at DESC);

-- Scan results: most-recent by ticker, by type
CREATE INDEX IF NOT EXISTS idx_scan_ticker_date
    ON scan_results (ticker, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_type_date
    ON scan_results (signal_type, detected_at DESC)
    WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_scan_active_recent
    ON scan_results (detected_at DESC)
    WHERE is_active = true;

-- News / disclosures: latest per ticker
CREATE INDEX IF NOT EXISTS idx_news_ticker_pub
    ON news (ticker, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_disclosures_ticker_date
    ON disclosures (ticker, filed_date DESC);

-- Alerts: unread for user
CREATE INDEX IF NOT EXISTS idx_alerts_user_unread
    ON alerts (user_id, created_at DESC)
    WHERE read_at IS NULL;

-- Trade log: chronological per user
CREATE INDEX IF NOT EXISTS idx_trade_log_user_date
    ON trade_log (user_id, trade_date DESC);

-- Bars (OHLCV): already PK (ticker, bar_date) but add btree on bar_date alone
-- for global "latest day" queries.
CREATE INDEX IF NOT EXISTS idx_bars_daily_date
    ON bars_daily (bar_date DESC);
