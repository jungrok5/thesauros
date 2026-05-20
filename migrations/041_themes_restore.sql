-- 041 — 테마 재활성화 (2026-05-19 search-only pivot 시 dropped)
--
-- 사용자 결정 (2026-05-20): 옛 Naver 테마 구현 부활 BUT 추천/점수 제거.
-- 변동률 시계열 (theme_daily) 도 제거 — 우리 DB 의 종목 데이터로
-- 사용자가 직접 분석. 페이지는 단순 list 만.

CREATE TABLE IF NOT EXISTS themes (
    theme_id    INT PRIMARY KEY,
    name        TEXT NOT NULL,
    -- members count snapshot at last sync — UI 의 "N 종목" 표시용.
    -- 정확한 종목 list 는 theme_members 에서 조회.
    members     INT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS theme_members (
    theme_id    INT NOT NULL REFERENCES themes(theme_id) ON DELETE CASCADE,
    ticker      VARCHAR(20) NOT NULL,
    -- ticker FK 안 검 — Naver 종목이 우리 tickers master 에 없을 수 있어서
    -- (옛 상장폐지 / KOSPI 종목인데 .KQ suffix 잘못 추정 등). UI 에서
    -- LEFT JOIN tickers 로 처리 — 매칭 안 되는 row 는 종목명만 표시 가능
    -- 또는 hide.
    PRIMARY KEY (theme_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_theme_members_ticker
    ON theme_members (ticker);

ALTER TABLE themes ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_members ENABLE ROW LEVEL SECURITY;

-- 공개 read (public market data). 옛 schema 따라.
CREATE POLICY p_themes_read ON themes FOR SELECT USING (true);
CREATE POLICY p_theme_members_read ON theme_members FOR SELECT USING (true);
