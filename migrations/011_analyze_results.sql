-- 011_analyze_results.sql — precomputed analyze() output per ticker
--
-- /stocks/[ticker] used to call FastAPI /api/book/analyze which ran
-- app.book.analyzer.analyze_ticker() on every request. That function is
-- already invoked inside scan_daily; we just weren't saving the full
-- result (only the extracted scan signals). This table stores the full
-- result so the site can SELECT it directly.

CREATE TABLE IF NOT EXISTS analyze_results (
    ticker VARCHAR(20) PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
    as_of DATE NOT NULL,
    last_close NUMERIC,
    action VARCHAR(20),                  -- STRONG_BUY / BUY / HOLD / SELL / SELL_OR_SHORT / AVOID
    book_score NUMERIC,
    result JSONB NOT NULL,               -- full AnalysisResult dict
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analyze_action ON analyze_results (action);
CREATE INDEX IF NOT EXISTS idx_analyze_updated ON analyze_results (updated_at DESC);

ALTER TABLE analyze_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyze_results FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_analyze_read ON analyze_results;
CREATE POLICY p_analyze_read ON analyze_results FOR SELECT
    TO authenticated, anon USING (true);
