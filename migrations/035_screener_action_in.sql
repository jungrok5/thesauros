-- 035 — screener: support actionIn (multi-action filter)
--
-- 사용자 보고 (2026-05-20): /screener?preset=book-buy 가 강매수 종목
-- 안 보임. book-buy preset 의 filter 가 action="BUY" 단일값이라
-- STRONG_BUY 종목들이 자동 제외됨. preset 설계 자체의 버그.
--
-- 수정: screener_results / screener_action_distribution 에 p_action_in
-- TEXT[] 추가. NULL 이면 무시, ANY-match 로 OR 필터.

DROP FUNCTION IF EXISTS screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,NUMERIC,INT
);

CREATE OR REPLACE FUNCTION screener_results(
    p_per_min          NUMERIC DEFAULT NULL,
    p_per_max          NUMERIC DEFAULT NULL,
    p_pbr_max          NUMERIC DEFAULT NULL,
    p_roe_min          NUMERIC DEFAULT NULL,
    p_debt_ratio_max   NUMERIC DEFAULT NULL,
    p_op_margin_min    NUMERIC DEFAULT NULL,
    p_revenue_growth_min NUMERIC DEFAULT NULL,
    p_passes_graham    BOOLEAN DEFAULT NULL,
    p_passes_buffett   BOOLEAN DEFAULT NULL,
    p_passes_magic     BOOLEAN DEFAULT NULL,
    p_passes_kang      BOOLEAN DEFAULT NULL,
    p_action           TEXT    DEFAULT NULL,
    p_action_in        TEXT[]  DEFAULT NULL,  -- ANY-match list
    p_book_score_min   NUMERIC DEFAULT NULL,
    p_limit            INT     DEFAULT 50
) RETURNS TABLE (
    ticker         VARCHAR(20),
    name           TEXT,
    per            NUMERIC,
    pbr            NUMERIC,
    roe            NUMERIC,
    debt_ratio     NUMERIC,
    op_margin      NUMERIC,
    revenue_growth NUMERIC,
    action         TEXT,
    book_score     NUMERIC
) AS $$
    SELECT
        f.ticker,
        t.name::TEXT,
        f.per, f.pbr, f.roe, f.debt_ratio, f.op_margin, f.revenue_growth,
        (a.result ->> 'action')::TEXT                 AS action,
        ((a.result ->> 'book_score')::NUMERIC)        AS book_score
      FROM factors_eval f
      LEFT JOIN tickers t ON t.ticker = f.ticker
      LEFT JOIN analyze_results a ON a.ticker = f.ticker
     WHERE
       (p_per_min IS NULL OR f.per >= p_per_min)
       AND (p_per_max IS NULL OR (f.per > 0 AND f.per <= p_per_max))
       AND (p_pbr_max IS NULL OR (f.pbr > 0 AND f.pbr <= p_pbr_max))
       AND (p_roe_min IS NULL OR f.roe >= p_roe_min)
       AND (p_debt_ratio_max IS NULL OR f.debt_ratio <= p_debt_ratio_max)
       AND (p_op_margin_min IS NULL OR f.op_margin >= p_op_margin_min)
       AND (p_revenue_growth_min IS NULL OR f.revenue_growth >= p_revenue_growth_min)
       AND (p_passes_graham IS NULL OR f.passes_graham = p_passes_graham)
       AND (p_passes_buffett IS NULL OR f.passes_buffett = p_passes_buffett)
       AND (p_passes_magic IS NULL OR f.passes_magic_formula = p_passes_magic)
       AND (p_passes_kang IS NULL OR f.passes_kang_value = p_passes_kang)
       AND (p_action IS NULL OR (a.result ->> 'action') = p_action)
       AND (p_action_in IS NULL OR (a.result ->> 'action') = ANY(p_action_in))
       AND (p_book_score_min IS NULL OR
            ((a.result ->> 'book_score')::NUMERIC) >= p_book_score_min)
     ORDER BY
       COALESCE((a.result ->> 'book_score')::NUMERIC, 0) DESC,
       COALESCE(f.roe, -1) DESC,
       f.ticker
     LIMIT p_limit;
$$ LANGUAGE sql STABLE;

GRANT EXECUTE ON FUNCTION screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT
) TO anon, authenticated, service_role;

-- Distribution function 도 같이 — preset 자체 분포는 action filter 와
-- 무관 (책 정신 통과 종목 중 강매수/매수/보류 분포 전체) 라 actionIn 불요.
-- 이미 migration 034 의 것 그대로 사용.
