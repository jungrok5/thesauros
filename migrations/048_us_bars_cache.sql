-- 048 — US ad-hoc analysis cache (Phase 6)
--
-- 미국 종목은 cron 으로 sync 안 함 (책 정신: 매매는 KR, 미국은 글로벌
-- 지수 + ad-hoc 분석). 사용자가 검색하면 Tiingo 에서 5년치 fetch +
-- 캐시. 7일 후 evict.
--
-- 참조: project_us_yfinance_blocked.md, TODO-Phase-6
-- 사전 작업: migration 045 (US universe drop)

-- ── us_bars: 검색-on-demand 캐시 ────────────────────────────────────
CREATE TABLE IF NOT EXISTS us_bars (
    ticker      TEXT NOT NULL,
    granularity TEXT NOT NULL CHECK (granularity IN ('W', 'M')),
    bar_date    DATE NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    adj_close   REAL,
    volume      BIGINT,
    PRIMARY KEY (ticker, granularity, bar_date)
);

CREATE INDEX IF NOT EXISTS idx_us_bars_ticker_gran
    ON us_bars (ticker, granularity, bar_date DESC);

-- ── us_ticker_cache: per-ticker meta (last_fetch, count, name) ─────
CREATE TABLE IF NOT EXISTS us_ticker_cache (
    ticker          TEXT PRIMARY KEY,
    name_en         TEXT,
    exchange        TEXT,
    sector          TEXT,
    last_bar_date   DATE,
    bars_count      INTEGER NOT NULL DEFAULT 0,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_us_ticker_cache_fetched
    ON us_ticker_cache (last_fetched_at);

-- ── RLS: read 누구나, write service-role 만 ─────────────────────────
ALTER TABLE us_bars ENABLE ROW LEVEL SECURITY;
ALTER TABLE us_ticker_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS us_bars_read ON us_bars;
CREATE POLICY us_bars_read ON us_bars FOR SELECT USING (true);

DROP POLICY IF EXISTS us_ticker_cache_read ON us_ticker_cache;
CREATE POLICY us_ticker_cache_read ON us_ticker_cache FOR SELECT USING (true);

-- Writes require service_role (no anon insert/update/delete).
DROP POLICY IF EXISTS us_bars_write ON us_bars;
CREATE POLICY us_bars_write ON us_bars FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS us_ticker_cache_write ON us_ticker_cache;
CREATE POLICY us_ticker_cache_write ON us_ticker_cache FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

COMMENT ON TABLE us_bars IS
  'Phase 6: ad-hoc 미국 주식 분석용 OHLCV 캐시. Tiingo API 에서 fetch, '
  '7일 후 us_ticker_cache 와 cascade evict. 책 정신상 매매는 KR.';

COMMENT ON TABLE us_ticker_cache IS
  'Phase 6: us_bars 의 per-ticker meta. last_fetched_at < NOW() - 7d → '
  'cron 에서 evict. 신규 검색 시 last_fetched_at refresh.';
