-- 029 — investor intelligence: earnings_calendar + analyst_consensus + institutional_ownership
--
-- 사용자 요청: 실적 발표 캘린더 / 컨센서스 목표주가 / 국민연금 등 큰손
-- 보유 비중. 세 가지 별도 테이블 — 각각 다른 소스 (DART / Naver / DART
-- 5% 보고) 에서 ingest.

-- ============================================================
-- earnings_calendar — 분기·연간 실적 발표 예정일
-- ============================================================
CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker         VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    expected_date  DATE NOT NULL,
    report_type    VARCHAR(20) NOT NULL,  -- 'Q1' | 'Q2' | 'Q3' | 'FY'
    -- 추정치 / 실적 — 둘 다 nullable (실적 전엔 consensus 만, 후엔 actual).
    consensus_eps  NUMERIC,
    actual_eps     NUMERIC,
    consensus_revenue NUMERIC,
    actual_revenue NUMERIC,
    source         VARCHAR(20) DEFAULT 'dart',   -- 'dart' | 'yahoo' (US)
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, expected_date, report_type)
);
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_expected
    ON earnings_calendar (expected_date);
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_ticker
    ON earnings_calendar (ticker, expected_date);

-- ============================================================
-- analyst_consensus — 애널리스트 컨센서스 (연도별)
-- ============================================================
CREATE TABLE IF NOT EXISTS analyst_consensus (
    ticker             VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    fiscal_year        INT NOT NULL,
    consensus_eps      NUMERIC,
    consensus_revenue  NUMERIC,
    consensus_op_income NUMERIC,
    target_price       NUMERIC,
    -- num_analysts: 컨센서스 평균에 기여한 애널리스트 수 — Naver 는 expose 안 함, NULL 가능.
    num_analysts       INT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_analyst_consensus_ticker
    ON analyst_consensus (ticker, fiscal_year DESC);

-- ============================================================
-- institutional_ownership — 대량보유 보고 (DART 5% 보고)
-- ============================================================
CREATE TABLE IF NOT EXISTS institutional_ownership (
    ticker         VARCHAR(20) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    -- 보유자 이름 (예: '국민연금공단', '미래에셋자산운용')
    holder_name    TEXT NOT NULL,
    -- 보유자 분류 — 'NPS' (국민연금) / 'AMC' (자산운용사) / 'FUND' / 'OTHER'
    holder_type    VARCHAR(10) NOT NULL DEFAULT 'OTHER',
    shares         BIGINT,           -- 보유 주식수
    share_pct      NUMERIC,          -- 보유 비중 (%)
    reported_date  DATE NOT NULL,    -- 5% 보고 신고일
    rcept_no       VARCHAR(20),      -- DART 접수번호 — link 용
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, holder_name, reported_date)
);
CREATE INDEX IF NOT EXISTS idx_institutional_ownership_ticker
    ON institutional_ownership (ticker, reported_date DESC);
CREATE INDEX IF NOT EXISTS idx_institutional_ownership_holder
    ON institutional_ownership (holder_name, reported_date DESC);

-- RLS — 모두 public read, service-key write.
ALTER TABLE earnings_calendar ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyst_consensus ENABLE ROW LEVEL SECURITY;
ALTER TABLE institutional_ownership ENABLE ROW LEVEL SECURITY;
