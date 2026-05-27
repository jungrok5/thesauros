-- 053 — factors_eval.market_cap 추가 + screener_results RPC 확장.
--
-- Why: 2026-05-27 그리드 서치 14변형 결과, "mid-cap sweet spot" (시총 5000억
-- 안팎의 중형주 우선) 가 모든 지표에서 1위 (CAGR +20.65%, DD 37.3%, Calmar 0.55).
-- production ranking 공식을 L2 = 80% book + 20% mid-cap-sweet 로 전환하기 위해
-- 시총 데이터를 RPC 결과에 포함.
--
-- 추가 컬럼:
--   factors_eval.market_cap NUMERIC — 최근 KRW 시가총액 (Naver mobile API)
--
-- screener_results 반환에 추가:
--   market_cap     NUMERIC — 위 컬럼
--   quality_score  INT     — ROE+ROA+op_margin 합산 (factors_eval 에 이미 있음)
--   safety_score   INT     — 부채비율 (factors_eval 에 이미 있음)
--
-- 백필: scripts/backfill_market_caps.py 를 별도 실행.

ALTER TABLE factors_eval
    ADD COLUMN IF NOT EXISTS market_cap NUMERIC;

COMMENT ON COLUMN factors_eval.market_cap IS
    'KRW market cap from Naver mobile API. Updated by eval_financials upsert.';

-- RPC 재정의 — 기존 시그니처 drop 후 추가 컬럼 반환.
DROP FUNCTION IF EXISTS screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT,
    TEXT,BOOLEAN,INT
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
    p_limit            INT     DEFAULT 50,
    p_quarter_zone       TEXT    DEFAULT NULL,
    p_volume_surge       BOOLEAN DEFAULT NULL,
    p_catalyst_max_weeks INT     DEFAULT NULL
) RETURNS TABLE (
    ticker              VARCHAR(20),
    name                TEXT,
    per                 NUMERIC,
    pbr                 NUMERIC,
    roe                 NUMERIC,
    debt_ratio          NUMERIC,
    op_margin           NUMERIC,
    revenue_growth      NUMERIC,
    action              TEXT,
    book_score          NUMERIC,
    volume_case_num     INT,
    volume_label        TEXT,
    volume_dir          TEXT,
    quarter_zone        TEXT,
    catalyst_bars_since INT,
    -- New 2026-05-27 (Phase 4 L2 mid-cap sweet)
    market_cap          NUMERIC,
    quality_score       INT,
    safety_score        INT
) AS $$
    SELECT
        f.ticker,
        t.name::TEXT,
        f.per, f.pbr, f.roe, f.debt_ratio, f.op_margin, f.revenue_growth,
        (a.result ->> 'action')::TEXT                              AS action,
        ((a.result ->> 'book_score')::NUMERIC)                     AS book_score,
        ((a.result -> 'volume_case' ->> 'case')::INT)              AS volume_case_num,
        (a.result -> 'volume_case' ->> 'label_kr')::TEXT           AS volume_label,
        (a.result -> 'volume_case' ->> 'direction')::TEXT          AS volume_dir,
        (a.result ->> 'quarter_zone')::TEXT                        AS quarter_zone,
        (
          SELECT MIN((p->'extra'->>'bars_since')::INT)
            FROM jsonb_array_elements(a.result->'patterns') p
           WHERE p->>'kind' ILIKE '%catalyst%'
             AND (p->'extra'->>'bars_since') ~ '^[0-9]+$'
        ) AS catalyst_bars_since,
        f.market_cap,
        f.quality_score,
        f.safety_score
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
       AND (p_quarter_zone IS NULL OR
            (a.result ->> 'quarter_zone') = p_quarter_zone)
       AND (p_volume_surge IS NULL OR p_volume_surge = FALSE OR
            (a.result -> 'volume_case' ->> 'case')::INT IN (3, 9))
       AND (p_catalyst_max_weeks IS NULL OR
            EXISTS (
              SELECT 1 FROM jsonb_array_elements(a.result->'patterns') p
              WHERE p->>'kind' ILIKE '%catalyst%'
                AND (p->'extra'->>'bars_since') ~ '^[0-9]+$'
                AND (p->'extra'->>'bars_since')::INT <= p_catalyst_max_weeks
            ))
     ORDER BY
       COALESCE((a.result ->> 'book_score')::NUMERIC, 0) DESC,
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
       COALESCE(f.roe, -1) DESC,
       f.ticker
     LIMIT p_limit;
$$ LANGUAGE sql STABLE;

GRANT EXECUTE ON FUNCTION screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT,
    TEXT,BOOLEAN,INT
) TO anon, authenticated, service_role;
