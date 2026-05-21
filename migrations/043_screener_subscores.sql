-- 043 — screener_results 확장: sub-score (volume / 4등분선 / catalyst) +
--       추가 필터 (quarter_zone / volume_surge / catalyst_fresh_weeks).
--
-- Why: book_score 가 trend 60% + pattern 30% + reversal 20% + volume 15%
-- 합산 → max 1.00 clamp 라 같은 1.00 만점이어도 "추세만 강함" 과 "거래량
-- 폭증 + 4등분선 safe + catalyst 직후" 차이를 사용자가 인지 못 했음.
-- 결과 row 에 sub-score chip 데이터 추가 + universe-wide 필터링 가능.
--
-- 새 컬럼 (총 5 개):
--   volume_case_num     INT       — 거래량 12 case 번호 (NULL = 분석 없음)
--   volume_label        TEXT      — "급증 + 큰 양봉" 같은 한글 label
--   volume_dir          TEXT      — bullish / bearish / neutral
--   quarter_zone        TEXT      — safe75 / warn50 / danger25 / broken / n/a
--   catalyst_bars_since INT       — 가장 최근 catalyst pattern 의 bars_since
--                                   (NULL 이면 catalyst 패턴 없음)
-- 새 필터 (3 개):
--   p_quarter_zone        TEXT    — 정확히 매치 (예: 'safe75')
--   p_volume_surge        BOOLEAN — case in (3, 9): "바닥 폭증" / "급등 양봉"
--   p_catalyst_max_weeks  INT     — catalyst_bars_since <= N (NULL 이면 무필터)

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
    p_limit            INT     DEFAULT 50,
    -- New 2026-05-21
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
    catalyst_bars_since INT
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
          -- 가장 최근 catalyst pattern 의 bars_since
          SELECT MIN((p->'extra'->>'bars_since')::INT)
            FROM jsonb_array_elements(a.result->'patterns') p
           WHERE p->>'kind' ILIKE '%catalyst%'
             AND (p->'extra'->>'bars_since') ~ '^[0-9]+$'
        ) AS catalyst_bars_since
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
