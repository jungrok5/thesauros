-- 012_chart_data.sql — precomputed chart payload per (ticker, timeframe)
--
-- Replaces FastAPI /api/book/chart. The daily scan computes the chart
-- payload (bars + MAs + completed patterns + quarter lines + last candle)
-- for each ticker, for daily/weekly/monthly. The site SELECTs it.

CREATE TABLE IF NOT EXISTS chart_data (
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    timeframe VARCHAR(10) NOT NULL,    -- 'daily' | 'weekly' | 'monthly'
    years INT NOT NULL DEFAULT 2,
    payload JSONB NOT NULL,             -- {bars, mas, patterns, quarter_lines, last_candle}
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, timeframe, years)
);

ALTER TABLE chart_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE chart_data FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_chart_read ON chart_data;
CREATE POLICY p_chart_read ON chart_data FOR SELECT
    TO authenticated, anon USING (true);
