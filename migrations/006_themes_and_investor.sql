-- 006_themes_and_investor.sql — KR theme classification + investor flow tables
-- Both come from public sources (Naver Finance + KIS API) and are useful
-- inputs for the "탑다운 3단계" (theme analysis) page.

-- ============================================================
-- KR themes (from Naver Finance theme list)
-- ============================================================
CREATE TABLE IF NOT EXISTS themes (
    theme_id INT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    members INT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS theme_daily (
    theme_id INT NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
    day DATE NOT NULL,
    change_pct_1d NUMERIC,
    change_pct_1m NUMERIC,
    leading_ticker VARCHAR(20) REFERENCES tickers(ticker),
    leading_name VARCHAR(120),
    lagging_ticker VARCHAR(20) REFERENCES tickers(ticker),
    lagging_name VARCHAR(120),
    PRIMARY KEY (theme_id, day)
);
CREATE INDEX IF NOT EXISTS idx_theme_daily_day
    ON theme_daily (day DESC, change_pct_1d DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS theme_members (
    theme_id INT NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    PRIMARY KEY (theme_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_theme_members_ticker
    ON theme_members (ticker);

-- ============================================================
-- KR investor flow (foreign + institutional + individual net buying)
-- Source: KIS API /uapi/domestic-stock/v1/quotations/inquire-investor
-- One row per (ticker, day). Values are KRW (억 단위는 UI에서 변환).
-- ============================================================
CREATE TABLE IF NOT EXISTS investor_flow (
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    day DATE NOT NULL,
    foreign_net NUMERIC,        -- 외국인 순매수 거래대금 (KRW)
    institution_net NUMERIC,    -- 기관 합산 순매수
    individual_net NUMERIC,     -- 개인 순매수
    program_net NUMERIC,        -- 프로그램 매매 순매수
    foreign_shares_net BIGINT,  -- 외국인 순매수 수량
    institution_shares_net BIGINT,
    individual_shares_net BIGINT,
    PRIMARY KEY (ticker, day)
);
CREATE INDEX IF NOT EXISTS idx_investor_flow_day
    ON investor_flow (day DESC);

-- ============================================================
-- RLS — both are market-data, public read OK
-- ============================================================
ALTER TABLE themes              ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_daily         ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_members       ENABLE ROW LEVEL SECURITY;
ALTER TABLE investor_flow       ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_themes_read ON themes;
CREATE POLICY p_themes_read ON themes FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS p_theme_daily_read ON theme_daily;
CREATE POLICY p_theme_daily_read ON theme_daily FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS p_theme_members_read ON theme_members;
CREATE POLICY p_theme_members_read ON theme_members FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS p_inv_flow_read ON investor_flow;
CREATE POLICY p_inv_flow_read ON investor_flow FOR SELECT TO anon, authenticated USING (true);
