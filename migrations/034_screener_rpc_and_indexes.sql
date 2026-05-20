-- 034 — screener RPC + 인덱스 보강
--
-- 사용자 피드백 (2026-05-20): "엄청 무식한 방법" — JS-side aggregation.
-- 다른 페이지도 audit:
--   - screener: 200 행 fetch + 3 query + JS filter+sort 패턴 (같은 유형)
--   - bars: PK (ticker, granularity, bar_date) 만 있어 volume_surges RPC 가
--           full scan (granularity, bar_date) 조건 매칭 안 됨

-- ============================================================
-- 1. bars 인덱스 — volume_surges RPC 가속
-- ============================================================
-- PK 는 (ticker, granularity, bar_date) 순서라 'W' + date 범위 쿼리에서는
-- 인덱스 사용 못 함 (ticker prefix 필요). granularity + bar_date 인덱스로
-- volume_surges RPC 의 WHERE granularity='W' AND bar_date >= ... 가 빨라짐.
CREATE INDEX IF NOT EXISTS idx_bars_granularity_date
    ON bars (granularity, bar_date DESC)
    INCLUDE (ticker, close, volume);  -- covering index — heap 안 가도 됨

-- ============================================================
-- 2. factors_eval 인덱스 — screener gate 필터 가속
-- ============================================================
-- 4 대 가치투자 gate 들은 boolean 컬럼. partial index 로 true 인 row 만
-- 인덱싱 (작아짐 + 빠름).
CREATE INDEX IF NOT EXISTS idx_factors_passes_graham
    ON factors_eval (per, pbr, roe) WHERE passes_graham = true;
CREATE INDEX IF NOT EXISTS idx_factors_passes_buffett
    ON factors_eval (per, pbr, roe) WHERE passes_buffett = true;
CREATE INDEX IF NOT EXISTS idx_factors_passes_magic
    ON factors_eval (per, pbr, roe) WHERE passes_magic_formula = true;
CREATE INDEX IF NOT EXISTS idx_factors_passes_kang
    ON factors_eval (per, pbr, roe) WHERE passes_kang_value = true;

-- ============================================================
-- 3. screener_results RPC — 단일 호출로 끝
-- ============================================================
-- 옛 방식: factors_eval × tickers × analyze_results 3 query + JS filter+sort.
-- 신: DB-side LEFT JOIN + WHERE + ORDER BY + LIMIT. analyze_results.result
-- 는 JSONB 라 -> 'action' 추출.
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
    p_action           TEXT    DEFAULT NULL,  -- 'BUY' | 'STRONG_BUY' etc
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
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,NUMERIC,INT
) TO anon, authenticated, service_role;

-- ============================================================
-- 4. screener_action_distribution RPC — 헤더 분포 chip
-- ============================================================
-- 페이지가 현재 통과 종목의 action 분포 (강매수/매수/보류/회피) 를 chip
-- 으로 보여줌. 옛날엔 50 결과 전체 받아서 JS Counter. 이제 DB-side COUNT.
CREATE OR REPLACE FUNCTION screener_action_distribution(
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
    p_passes_kang      BOOLEAN DEFAULT NULL
) RETURNS TABLE (
    strong_buy INT, buy INT, hold INT, avoid INT, unanalyzed INT
) AS $$
    WITH base AS (
        SELECT (a.result ->> 'action') AS act
          FROM factors_eval f
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
    )
    SELECT
        COUNT(*) FILTER (WHERE act = 'STRONG_BUY')::INT,
        COUNT(*) FILTER (WHERE act = 'BUY')::INT,
        COUNT(*) FILTER (WHERE act = 'HOLD')::INT,
        COUNT(*) FILTER (WHERE act IN ('AVOID','SELL','SELL_OR_SHORT'))::INT,
        COUNT(*) FILTER (WHERE act IS NULL)::INT
      FROM base;
$$ LANGUAGE sql STABLE;

GRANT EXECUTE ON FUNCTION screener_action_distribution(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN
) TO anon, authenticated, service_role;
