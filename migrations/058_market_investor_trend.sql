-- 058 — market-wide investor trend (KOSPI / KOSDAQ).
--
-- Source: m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/integration
--   dealTrendInfo: { personalValue, foreignValue, institutionalValue }
--   (values are KRW 백만, signed; "+" buy / "-" sell)
--
-- Why only 3 categories: 5-axis reconnaissance (2026-05-28) confirmed that
-- the 7-type breakdown (금융투자/보험/투신/사모/은행/기타금융/연기금) is NOT
-- available from any cloud-reachable Naver endpoint. finance.naver.com's
-- investorDealTrendDay.naver returns empty body for all bizdate values,
-- even via real-browser Playwright. KRX is cloud-blocked (Azure IP filter).
-- Mirrors the per-ticker investor_flow model — same 3-axis shape.
--
-- Backfill: not possible from this endpoint (snapshot returns today only).
-- Daily cron accumulates one row per (market, day) going forward.

CREATE TABLE IF NOT EXISTS market_investor_trend (
    market VARCHAR(8) NOT NULL,            -- 'KOSPI' or 'KOSDAQ'
    day DATE NOT NULL,
    individual_net NUMERIC,                -- 개인 (KRW 백만)
    foreign_net NUMERIC,                   -- 외국인
    institution_net NUMERIC,               -- 기관계
    PRIMARY KEY (market, day)
);

CREATE INDEX IF NOT EXISTS idx_market_investor_trend_day
    ON market_investor_trend (day DESC);

-- RLS — market-data, public read OK.
ALTER TABLE market_investor_trend ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_market_inv_trend_read ON market_investor_trend;
CREATE POLICY p_market_inv_trend_read ON market_investor_trend
    FOR SELECT TO anon, authenticated USING (true);

COMMENT ON TABLE market_investor_trend IS
    'Market-wide daily net buying by 개인/외국인/기관계 (KRW 백만). KOSPI and KOSDAQ. Source: m.stock.naver.com integration API. 3-axis only — 7-type breakdown not cloud-reachable.';
