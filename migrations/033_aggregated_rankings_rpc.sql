-- 033 — RPC functions for server-side aggregation
--
-- 사용자 audit (2026-05-20): /flow-ranking + /volume-surge 페이지가
-- 데이터의 4% 만 사용. PostgREST 의 max-rows hard cap = 1000 이라
-- .limit(50000) 명시해도 무시됨. 결과:
--   - investor_flow 27K rows → 첫 1K 만 → 랭킹 부정확
--   - bars (W) 26K rows → 첫 1K 만 → 폭증 종목 누락
--
-- Fix: 서버측 GROUP BY 로 ticker 별 집계 후 작은 응답 (~3K 종목)만 전송.

-- ============================================================
-- top_flow_rankings: 외인+기관 14일 누적 매수/매도 TOP N
-- ============================================================
CREATE OR REPLACE FUNCTION top_flow_rankings(
    p_days_back INT DEFAULT 14,
    p_limit     INT DEFAULT 30,
    p_direction TEXT DEFAULT 'buy'  -- 'buy' | 'sell'
) RETURNS TABLE (
    ticker          VARCHAR(20),
    foreign_sum     NUMERIC,
    institution_sum NUMERIC,
    combined_sum    NUMERIC,
    days            INT
) AS $$
    SELECT
        ticker,
        SUM(foreign_net)::NUMERIC          AS foreign_sum,
        SUM(institution_net)::NUMERIC      AS institution_sum,
        SUM(COALESCE(foreign_net,0) + COALESCE(institution_net,0))::NUMERIC AS combined_sum,
        COUNT(*)::INT                       AS days
      FROM investor_flow
     WHERE day >= CURRENT_DATE - (p_days_back || ' days')::INTERVAL
     GROUP BY ticker
     ORDER BY
       CASE WHEN p_direction = 'buy'
            THEN SUM(COALESCE(foreign_net,0) + COALESCE(institution_net,0))
            ELSE -SUM(COALESCE(foreign_net,0) + COALESCE(institution_net,0))
       END DESC
     LIMIT p_limit;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- volume_surges: 이번주 거래량이 직전 8주 평균의 2 배 이상인 종목
-- ============================================================
CREATE OR REPLACE FUNCTION volume_surges(
    p_min_ratio       NUMERIC DEFAULT 2.0,
    p_min_samples     INT     DEFAULT 4,
    p_limit           INT     DEFAULT 30
) RETURNS TABLE (
    ticker            VARCHAR(20),
    this_week_vol     BIGINT,
    avg_vol           NUMERIC,
    ratio             NUMERIC,
    this_week_close   NUMERIC,
    prev_week_close   NUMERIC,
    price_change_pct  NUMERIC
) AS $$
    WITH ranked AS (
        SELECT ticker, bar_date, close, volume,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY bar_date DESC) AS rn
          FROM bars
         WHERE granularity = 'W'
           AND bar_date >= CURRENT_DATE - INTERVAL '9 weeks'
    ),
    pivoted AS (
        SELECT
            ticker,
            MAX(CASE WHEN rn = 1 THEN volume END)             AS this_vol,
            MAX(CASE WHEN rn = 1 THEN close  END)::NUMERIC    AS this_close,
            MAX(CASE WHEN rn = 2 THEN close  END)::NUMERIC    AS prev_close,
            AVG(CASE WHEN rn BETWEEN 2 AND 9 AND volume > 0 THEN volume END)
                ::NUMERIC                                      AS avg_vol_calc,
            COUNT(CASE WHEN rn BETWEEN 2 AND 9 AND volume > 0 THEN 1 END)
                ::INT                                          AS sample_n
          FROM ranked
         GROUP BY ticker
    )
    SELECT
        ticker,
        this_vol                                  AS this_week_vol,
        avg_vol_calc                              AS avg_vol,
        (this_vol::NUMERIC / NULLIF(avg_vol_calc, 0))::NUMERIC AS ratio,
        this_close                                AS this_week_close,
        prev_close                                AS prev_week_close,
        CASE WHEN prev_close > 0
             THEN ((this_close / prev_close) - 1) * 100
             ELSE 0
        END                                       AS price_change_pct
      FROM pivoted
     WHERE this_vol IS NOT NULL
       AND avg_vol_calc IS NOT NULL
       AND avg_vol_calc > 0
       AND sample_n >= p_min_samples
       AND (this_vol::NUMERIC / avg_vol_calc) >= p_min_ratio
     ORDER BY (this_vol::NUMERIC / avg_vol_calc) DESC
     LIMIT p_limit;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- Grant execute to authenticated + anon (PostgREST RPC access).
-- ============================================================
GRANT EXECUTE ON FUNCTION top_flow_rankings(INT,INT,TEXT)   TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION volume_surges(NUMERIC,INT,INT)     TO anon, authenticated, service_role;
