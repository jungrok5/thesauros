-- 037 — 단일 ticker 의 volume surge 정보 RPC
--
-- 사용자 요청 (2026-05-20): 거래량 폭증 페이지의 정보 (이번주 vol /
-- 8주 평균 / ratio / 가격 변동) 가 종목 상세 페이지에도 카드로 표시돼야.
-- 폭증 목록에 안 잡힌 종목도 라이브 ratio 보여주면 도움.
--
-- 기존 volume_surges() 는 ratio >= 2.0 만 반환. 단일 ticker 용은 ratio
-- 무관 (1.0 도 표시). 페이지가 ratio 보고 카드 톤 결정.

CREATE OR REPLACE FUNCTION volume_surge_for_ticker(
    p_ticker VARCHAR(20)
) RETURNS TABLE (
    this_week_vol     BIGINT,
    avg_vol           NUMERIC,
    ratio             NUMERIC,
    this_week_close   NUMERIC,
    prev_week_close   NUMERIC,
    price_change_pct  NUMERIC,
    sample_n          INT
) AS $$
    WITH ranked AS (
        SELECT bar_date, close, volume,
               ROW_NUMBER() OVER (ORDER BY bar_date DESC) AS rn
          FROM bars
         WHERE ticker = p_ticker
           AND granularity = 'W'
           AND bar_date >= CURRENT_DATE - INTERVAL '9 weeks'
    ),
    pivoted AS (
        SELECT
            MAX(CASE WHEN rn = 1 THEN volume END)             AS this_vol,
            MAX(CASE WHEN rn = 1 THEN close  END)::NUMERIC    AS this_close,
            MAX(CASE WHEN rn = 2 THEN close  END)::NUMERIC    AS prev_close,
            AVG(CASE WHEN rn BETWEEN 2 AND 9 AND volume > 0 THEN volume END)
                ::NUMERIC                                      AS avg_vol_calc,
            COUNT(CASE WHEN rn BETWEEN 2 AND 9 AND volume > 0 THEN 1 END)
                ::INT                                          AS sample_n
          FROM ranked
    )
    SELECT
        this_vol         AS this_week_vol,
        avg_vol_calc     AS avg_vol,
        CASE WHEN avg_vol_calc > 0
             THEN (this_vol::NUMERIC / avg_vol_calc)
             ELSE NULL
        END              AS ratio,
        this_close       AS this_week_close,
        prev_close       AS prev_week_close,
        CASE WHEN prev_close > 0
             THEN ((this_close / prev_close) - 1) * 100
             ELSE NULL
        END              AS price_change_pct,
        sample_n
      FROM pivoted
     WHERE this_vol IS NOT NULL;
$$ LANGUAGE sql STABLE;

GRANT EXECUTE ON FUNCTION volume_surge_for_ticker(VARCHAR)
    TO anon, authenticated, service_role;
