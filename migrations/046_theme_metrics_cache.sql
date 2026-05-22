-- 046 — theme_metrics_cache: weekly-refreshed snapshot of theme_metrics()
--
-- 문제: theme_metrics() RPC 가 cold 9-10초 (645k bars 행 윈도우 정렬).
-- 매 /themes 페이지 로드마다 그 비용을 치르면 Vercel 10s timeout 빠듯
-- → 빈 응답 → "테마 데이터 없음" placeholder. P_THEME (직전 P1 fix 의
-- ISR + maxDuration 픽스는 즉시 패치) 의 근본 해결: 결과를 일반 테이블에
-- 캐시 + weekly cron 으로 refresh. themes 데이터는 weekly 갱신이라
-- 신선도 충분.
--
-- 스키마: theme_metrics() RPC 의 RETURNS TABLE 시그니처와 1:1 매칭.
-- weekly cron 이 `INSERT INTO ... SELECT * FROM theme_metrics()` 한 번에
-- 갱신 (또는 TRUNCATE + INSERT 두 단계 — implementation detail).
--
-- 페이지: /themes 가 RPC 직접 호출 대신 이 테이블 SELECT → 10ms 응답.

CREATE TABLE IF NOT EXISTS theme_metrics_cache (
    theme_id        INT PRIMARY KEY,
    name            TEXT NOT NULL,
    members         INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    avg_change_pct  NUMERIC,
    up_count        INT NOT NULL DEFAULT 0,
    down_count      INT NOT NULL DEFAULT 0,
    strong_buy      INT NOT NULL DEFAULT 0,
    buy             INT NOT NULL DEFAULT 0,
    hold            INT NOT NULL DEFAULT 0,
    avoid           INT NOT NULL DEFAULT 0,
    top_tickers     TEXT[],
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 정렬 후보 (page 의 sortBy 가 SQL 로 가능하도록).
CREATE INDEX IF NOT EXISTS idx_theme_metrics_cache_avg_change
    ON theme_metrics_cache (avg_change_pct DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_theme_metrics_cache_members
    ON theme_metrics_cache (members DESC);

-- RLS: 누구나 읽기 가능 (테마는 공개 데이터). 쓰기는 service role only.
ALTER TABLE theme_metrics_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_theme_cache_read ON theme_metrics_cache;
CREATE POLICY p_theme_cache_read ON theme_metrics_cache
    FOR SELECT TO anon, authenticated USING (true);
-- 쓰기 정책 없음 → service role bypass 만 가능.

COMMENT ON TABLE theme_metrics_cache IS
  'theme_metrics() RPC 결과 캐시. weekly cron 이 갱신. /themes 페이지는'
  ' 이 테이블 SELECT 만 (RPC 직접 호출 X).';

-- Publish 헬퍼는 Python 측 `app.db.publish_theme_metrics` 모듈이
-- 담당. 처음엔 RPC + SECURITY DEFINER 로 짰지만 theme_metrics() 의 inline
-- expansion 단계에서 search_path 가 안 잡혀 theme_members 를 못 찾았다.
-- Python 측 service-role connection 으로 단순 INSERT + TRUNCATE 가 더
-- 깔끔하고 schema 이슈에서 자유롭다.
