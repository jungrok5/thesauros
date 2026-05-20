-- 036 — screener 정렬에 action priority 추가
--
-- 사용자 보고 (2026-05-20): 결과 리스트가 "강매수 → 보류 → 강매수" 처럼
-- 섞여서 정렬 기준이 헷갈림. 현재 ORDER BY: book_score DESC 만 + roe.
--
-- 수정: secondary key 로 action priority 추가. 같은 점수 안에서는
-- 강매수 → 매수 → 보류 → 분석대기 → 회피 순으로 나열.
--   STRONG_BUY = 5
--   BUY        = 4
--   HOLD       = 3
--   NULL       = 2 (분석 대기)
--   SELL/AVOID/SELL_OR_SHORT = 1

DROP FUNCTION IF EXISTS screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT
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
    p_action_in        TEXT[]  DEFAULT NULL,
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
       -- 1) 책 점수 — 가장 강한 매수 신호 우선
       COALESCE((a.result ->> 'book_score')::NUMERIC, 0) DESC,
       -- 2) action priority — 같은 점수면 강매수 → 매수 → 보류 → 회피
       CASE (a.result ->> 'action')
         WHEN 'STRONG_BUY'     THEN 5
         WHEN 'BUY'            THEN 4
         WHEN 'HOLD'           THEN 3
         WHEN NULL             THEN 2
         WHEN 'AVOID'          THEN 1
         WHEN 'SELL'           THEN 1
         WHEN 'SELL_OR_SHORT'  THEN 1
         ELSE 2
       END DESC,
       -- 3) ROE — 펀더 강도 tie-breaker
       COALESCE(f.roe, -1) DESC,
       f.ticker
     LIMIT p_limit;
$$ LANGUAGE sql STABLE;

GRANT EXECUTE ON FUNCTION screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT
) TO anon, authenticated, service_role;
