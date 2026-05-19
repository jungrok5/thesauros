-- 027 — 시장 신호: 경고 라벨 + 공매도 + 배당
--
-- 사용자 요청 (2026-05-19): 단순 데이터 표시가 아니라 "이런 상황이니 이렇게
-- 하라"는 액션을 함께. 책 정신 (추세추종 + 자본 보전) 톤 유지.
--
--   market_warnings — KRX 시장조치 (관리/거래정지/투자경고 등). 매수 자체를
--                     차단해야 하는 critical 정보.
--   short_sales    — 일별 공매도 비중 + 잔고. 비중 ↑ = 약세/squeeze 위험.
--   dividend_info  — 배당락일 + 수익률. 배당락 ≈ price drop ≠ 매도 신호.

-- ============================================================
-- market_warnings — 현재 활성 경고만 (시장조치)
-- ============================================================
CREATE TABLE IF NOT EXISTS market_warnings (
    ticker        VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    -- 레벨 — UI tone 매핑용. KRX 공식 명칭과 매칭:
    --   trading_halt  → 거래정지 (🔴 매수 차단)
    --   surveillance  → 관리종목 (🔴 매수 차단)
    --   risk          → 투자위험 (🔴 강한 경고)
    --   warning       → 투자경고 (🟠 경고)
    --   caution       → 투자주의 (🟡 주의)
    --   overheat      → 단기과열 (🟡 주의 — 변동성 ↑)
    level         VARCHAR(20) NOT NULL CHECK (level IN (
        'trading_halt', 'surveillance', 'risk', 'warning', 'caution', 'overheat'
    )),
    reason        TEXT,
    designated_at DATE,
    -- 만료 예정일 — KRX 가 사전 공시하는 종료일. NULL = 무기한 (해제 시까지).
    expires_at    DATE,
    source        VARCHAR(20) DEFAULT 'naver',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, level)
);
CREATE INDEX IF NOT EXISTS idx_market_warnings_ticker
    ON market_warnings (ticker);
CREATE INDEX IF NOT EXISTS idx_market_warnings_level
    ON market_warnings (level);

-- ============================================================
-- short_sales — 일별 공매도 거래량 + 잔고
-- ============================================================
CREATE TABLE IF NOT EXISTS short_sales (
    ticker            VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    day               DATE NOT NULL,
    short_volume      BIGINT,           -- 당일 공매도 체결 주식수
    short_value       NUMERIC,          -- 당일 공매도 거래대금 (원)
    total_volume      BIGINT,           -- 당일 전체 거래량 (비율 계산용)
    short_ratio       NUMERIC,          -- short_volume / total_volume
    -- 잔고 (누적) — 일 단위로 KRX 가 공시
    balance_shares    BIGINT,
    balance_value     NUMERIC,
    balance_ratio     NUMERIC,          -- balance_shares / 상장주식수
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, day)
);
CREATE INDEX IF NOT EXISTS idx_short_sales_ticker_day
    ON short_sales (ticker, day DESC);

-- ============================================================
-- dividend_info — 종목별 최신 배당 일정 + 수익률
-- ============================================================
CREATE TABLE IF NOT EXISTS dividend_info (
    ticker         VARCHAR(20) PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
    -- 가장 최근 / 예정된 배당
    ex_dividend    DATE,          -- 배당락일 (매수해도 배당 못 받는 첫 날)
    record_date    DATE,          -- 기준일
    payment_date   DATE,          -- 지급일
    dps            NUMERIC,       -- 주당 배당금 (원)
    yield_pct      NUMERIC,       -- 배당수익률 (%)
    -- 시계열은 DPS / BPS / EPS 가 fundamentals 테이블에 이미 적재됨.
    -- 이 테이블은 "다음 배당락이 언제냐 + 얼마받냐" 를 빠르게 조회하기 위함.
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS — 시장 정보는 모두 public read. 서비스 키만 쓰기.
ALTER TABLE market_warnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE short_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE dividend_info ENABLE ROW LEVEL SECURITY;
-- 서버 컴포넌트가 service-key 로 직접 읽으므로 별도 SELECT 정책 불필요.
