-- 002_core_schema.sql — core tables for users / tickers / signals / alerts
-- Designed for: book-faithful KR+US trading recommendation site.
-- All tables get RLS (policies in 003_rls.sql).

-- ============================================================
-- USERS (authenticated via NextAuth Google OAuth on the Next.js side)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    telegram_chat_id VARCHAR(64),
    telegram_link_token VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TICKERS  master  (KOSPI / KOSDAQ / NASDAQ ...)
-- ============================================================
CREATE TABLE IF NOT EXISTS tickers (
    ticker VARCHAR(20) PRIMARY KEY,                -- "005930.KS", "AAPL"
    name VARCHAR(255) NOT NULL,
    market VARCHAR(20) NOT NULL,                   -- "KOSPI" | "KOSDAQ" | "NASDAQ" | "NYSE"
    sector VARCHAR(100),
    industry VARCHAR(100),
    listed_at DATE,
    delisted_at DATE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- WATCHLIST  (per user)
-- ============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    category VARCHAR(20) NOT NULL DEFAULT 'observing',  -- 'observing' | 'holding'
    entry_price NUMERIC,
    entry_date DATE,
    note TEXT,
    alerts_enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, ticker)
);

-- ============================================================
-- TRADE LOG  (user-recorded buys/sells)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    action VARCHAR(10) NOT NULL,                   -- 'buy' | 'sell'
    price NUMERIC NOT NULL,
    quantity INT,
    trade_date DATE NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- SCAN RESULTS  (book-rule signals detected daily/weekly/monthly)
-- ============================================================
CREATE TABLE IF NOT EXISTS scan_results (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    signal_type VARCHAR(50) NOT NULL,
        -- 17 book signals + book-v4 4-state:
        -- 'weekly_ma240_breakout', 'monthly_forking',
        -- 'pseki_oksuk_a' (240MA 밑 쌍바닥 = 피에스케이형),
        -- 'pseki_oksuk_b' (240MA 가운데 둔 쌍바닥 = 엘앤씨바이오형),
        -- 'pseki_oksuk_c' (240MA 가운데 둔 역H&S = 일동홀딩스형),
        -- 'pseki_oksuk_d' (240MA 다중바닥 = 디아이씨형),
        -- 'doulbanji' (돌반지: 후킹→펌핑→랠리),
        -- 'double_bottom', 'inverse_hns', 'triple_bottom', 'cup_handle',
        -- 'accumulation_5331', 'reverse_accumulation',
        -- 'retracement_1','retracement_2','retracement_3','retracement_4',
        -- 'platform_pattern',
        -- 'death_messenger_candle' (저승사자 — EXIT),
        -- 'ma240_break_down' (240MA 이탈 — EXIT),
        -- 'book_v4_enter','book_v4_pyramid','book_v4_warn','book_v4_exit'
    timeframe VARCHAR(10) NOT NULL,                -- 'daily' | 'weekly' | 'monthly'
    detected_at TIMESTAMPTZ NOT NULL,              -- detection bar's close-time
    strength NUMERIC DEFAULT 0.5,                  -- 0..1 (book reliability × recency)
    reason TEXT,                                    -- one-line Korean explanation
    params JSONB,                                   -- pattern parameters (entry/stop, etc.)
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- NEWS  (titles + links only; no LLM summary)
-- ============================================================
CREATE TABLE IF NOT EXISTS news (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) REFERENCES tickers(ticker),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source VARCHAR(50),                            -- '한경', '매경', '연합', 'NaverFinance' ...
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(url)
);

-- ============================================================
-- DISCLOSURES  (DART filings — titles + links + report type)
-- ============================================================
CREATE TABLE IF NOT EXISTS disclosures (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) REFERENCES tickers(ticker),
    rcept_no VARCHAR(20) NOT NULL,
    report_nm TEXT NOT NULL,
    report_type VARCHAR(50),                       -- 'A'=정기, 'B'=주요사항, ...
    filed_date DATE,
    url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(rcept_no)
);

-- ============================================================
-- FINANCIALS  evaluation cache (rule-based, no LLM)
-- ============================================================
CREATE TABLE IF NOT EXISTS financials_eval (
    ticker VARCHAR(20) PRIMARY KEY REFERENCES tickers(ticker),
    -- 3-year time series (JSONB: {fy: value})
    revenue_3y JSONB,
    operating_income_3y JSONB,
    net_income_3y JSONB,
    assets_3y JSONB,
    debt_3y JSONB,
    equity_3y JSONB,
    -- derived single-value metrics (latest)
    debt_ratio NUMERIC,
    roe NUMERIC,
    roa NUMERIC,
    op_margin NUMERIC,
    revenue_growth_yoy NUMERIC,
    net_income_growth_yoy NUMERIC,
    current_ratio NUMERIC,
    f_score INT,
    -- rule-based evaluations
    rules_eval JSONB,                              -- {debt:'안전', roe:'우수', ...}
    composite_score INT,                           -- 0..10
    summary_text TEXT,                             -- generated one-paragraph
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- FACTORS  (per-ticker factor values + industry percentile + rule eval)
-- ============================================================
CREATE TABLE IF NOT EXISTS factors_eval (
    ticker VARCHAR(20) PRIMARY KEY REFERENCES tickers(ticker),
    per NUMERIC, per_pctile NUMERIC, per_eval VARCHAR(20),
    pbr NUMERIC, pbr_pctile NUMERIC, pbr_eval VARCHAR(20),
    roe NUMERIC, roe_pctile NUMERIC, roe_eval VARCHAR(20),
    roa NUMERIC, roa_pctile NUMERIC, roa_eval VARCHAR(20),
    op_margin NUMERIC, op_margin_pctile NUMERIC, op_margin_eval VARCHAR(20),
    debt_ratio NUMERIC, debt_ratio_pctile NUMERIC, debt_ratio_eval VARCHAR(20),
    revenue_growth NUMERIC, revenue_growth_pctile NUMERIC,
    -- composite checks (book + academia)
    passes_kang_value BOOLEAN,
    passes_graham BOOLEAN,
    passes_magic_formula BOOLEAN,
    passes_buffett BOOLEAN,
    -- 4-axis scores
    value_score INT,
    growth_score INT,
    safety_score INT,
    quality_score INT,
    summary_text TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ALERTS  (telegram + in-page notifications)
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(20) REFERENCES tickers(ticker),
    alert_type VARCHAR(50) NOT NULL,
        -- 'enter' | 'pyramid' | 'warn' | 'exit'
        -- 'ma240_break' | 'ma10_break' | 'quarter_25_break'
    message TEXT NOT NULL,
    severity VARCHAR(10) NOT NULL DEFAULT 'info',  -- 'info' | 'warn' | 'critical'
    sent_telegram BOOLEAN NOT NULL DEFAULT false,
    sent_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ALERT PREFERENCES  (per user)
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enable_enter BOOLEAN NOT NULL DEFAULT true,
    enable_pyramid BOOLEAN NOT NULL DEFAULT true,
    enable_warn BOOLEAN NOT NULL DEFAULT true,
    enable_exit BOOLEAN NOT NULL DEFAULT true,    -- effectively forced
    enable_ma240_break BOOLEAN NOT NULL DEFAULT true,
    enable_quarter_25_break BOOLEAN NOT NULL DEFAULT true,
    enable_daily_top5 BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- MACRO STATE  (singleton — latest macro dashboard snapshot)
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_state (
    id INT PRIMARY KEY DEFAULT 1,
    global_status VARCHAR(20),                     -- 'bull' | 'bear' | 'mixed'
    kr_status VARCHAR(20),
    indices JSONB,                                  -- {nasdaq:'bull', sp500:'bull', ...}
    macro_indicators JSONB,                         -- all 47 with current value+eval
    mv_pq_signal VARCHAR(30),
    dial_scores JSONB,                              -- {liquidity:5,rate:4,cycle:5,price:4,fear:5}
    one_line_guidance TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (id = 1)
);

-- ============================================================
-- BARS  (daily OHLCV cache — used by chart overlay API and signal scans)
-- ============================================================
CREATE TABLE IF NOT EXISTS bars_daily (
    ticker VARCHAR(20) NOT NULL REFERENCES tickers(ticker),
    bar_date DATE NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    adj_close NUMERIC,
    volume BIGINT,
    PRIMARY KEY (ticker, bar_date)
);

-- ============================================================
-- HEALTH PING  (keepalive — avoid Supabase free-tier inactivity pause)
-- ============================================================
CREATE TABLE IF NOT EXISTS health_ping (
    id INT PRIMARY KEY DEFAULT 1,
    pinged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (id = 1)
);
INSERT INTO health_ping (id, pinged_at) VALUES (1, now())
ON CONFLICT (id) DO NOTHING;
