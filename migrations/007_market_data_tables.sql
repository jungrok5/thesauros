-- 007_market_data_tables.sql — migrate market data from local DuckDB
-- to Supabase so the deployed app stays self-contained (no DuckDB).
-- Scope is kept tight: prices last 8y, fundamentals FY-only since 2020,
-- macro full. Estimated combined size ≈ 340 MB (well within free 500MB).

-- ============================================================
-- bars_daily already exists (from migrations/002). Re-confirm shape
-- and add expression index on date for global "today" queries.
-- ============================================================
-- (already created in 002)
ALTER TABLE bars_daily ADD COLUMN IF NOT EXISTS adj_close NUMERIC;

-- ============================================================
-- fundamentals — annual statements only (FY rows). KR uses DART concepts;
-- US uses SEC XBRL. Both fit the same shape.
-- ============================================================
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker      VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    concept     VARCHAR(100) NOT NULL,
    fy          INT NOT NULL,
    period_end  DATE,
    filed_date  DATE,
    value       NUMERIC,
    unit        VARCHAR(10),
    PRIMARY KEY (ticker, concept, fy)
);
CREATE INDEX IF NOT EXISTS idx_fund_ticker_concept
    ON fundamentals (ticker, concept);
CREATE INDEX IF NOT EXISTS idx_fund_ticker_fy_desc
    ON fundamentals (ticker, fy DESC);

-- ============================================================
-- macro — FRED + yfinance time series, one row per (series_id, date)
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_series (
    series_id   VARCHAR(40) NOT NULL,
    date        DATE NOT NULL,
    value       NUMERIC,
    PRIMARY KEY (series_id, date)
);
CREATE INDEX IF NOT EXISTS idx_macro_series_date
    ON macro_series (series_id, date DESC);

-- ============================================================
-- RLS — public read on all three (market data, not user-specific)
-- ============================================================
ALTER TABLE fundamentals   ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_series   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_fundamentals_read ON fundamentals;
CREATE POLICY p_fundamentals_read ON fundamentals
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_macro_series_read ON macro_series;
CREATE POLICY p_macro_series_read ON macro_series
    FOR SELECT TO anon, authenticated USING (true);
