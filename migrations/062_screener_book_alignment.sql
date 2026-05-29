-- 062 — Align `screener_results` RPC with the book-faithful production
--        spec by (1) restricting candidates to tickers that have an
--        active top-5 entry signal firing and (2) returning the ticker's
--        industry so the page can enforce sector_cap=1 client-side.
--
-- Production buy logic per memory project_book_faithful_backtest:
--   entry signals = DEFAULT_ENTRY_SIGNALS in app/backtest/portfolio.py
--                 = (volume_case_3, pattern_forking, volume_case_7,
--                    action_strong_buy, pattern_ma240_breakout)
--   sector cap    = 1 per ISO-week per industry (now per snapshot)
--
-- Before this migration the page showed any high-book_score ticker
-- even if NONE of the top-5 signals fired this week, breaking the
-- "한 알고리즘 셋이 공유" invariant (backtest filters by signal_type;
-- screener didn't). Now they match.

DROP FUNCTION IF EXISTS screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT,
    TEXT,BOOLEAN,INT
);

CREATE OR REPLACE FUNCTION screener_results(
    p_per_min            NUMERIC DEFAULT NULL,
    p_per_max            NUMERIC DEFAULT NULL,
    p_pbr_max            NUMERIC DEFAULT NULL,
    p_roe_min            NUMERIC DEFAULT NULL,
    p_debt_ratio_max     NUMERIC DEFAULT NULL,
    p_op_margin_min      NUMERIC DEFAULT NULL,
    p_revenue_growth_min NUMERIC DEFAULT NULL,
    p_passes_graham      BOOLEAN DEFAULT NULL,
    p_passes_buffett     BOOLEAN DEFAULT NULL,
    p_passes_magic       BOOLEAN DEFAULT NULL,
    p_passes_kang        BOOLEAN DEFAULT NULL,
    p_action             TEXT    DEFAULT NULL,
    p_action_in          TEXT[]  DEFAULT NULL,
    p_book_score_min     NUMERIC DEFAULT NULL,
    p_limit              INT     DEFAULT 50,
    p_quarter_zone       TEXT    DEFAULT NULL,
    p_volume_surge       BOOLEAN DEFAULT NULL,
    p_catalyst_max_weeks INT     DEFAULT NULL,
    p_book_entry_only    BOOLEAN DEFAULT NULL    -- 2026-05-29 (NEW): when
                                                  -- TRUE, only tickers with
                                                  -- an active scan_results
                                                  -- row in the top-5 entry
                                                  -- signal set.
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
    market_cap          NUMERIC,
    quality_score       INT,
    safety_score        INT,
    industry            TEXT     -- 2026-05-29 (NEW): for sector_cap=1
                                  -- post-processing in page.tsx
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
        f.safety_score,
        t.industry::TEXT
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
       AND (p_book_entry_only IS NULL OR p_book_entry_only = FALSE OR
            EXISTS (
              SELECT 1 FROM scan_results sr
              WHERE sr.ticker = f.ticker
                AND sr.is_active = TRUE
                AND sr.signal_type IN (
                    'volume_case_3', 'pattern_forking', 'volume_case_7',
                    'action_strong_buy', 'pattern_ma240_breakout'
                )
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
$$ LANGUAGE sql STABLE
SET search_path = public, pg_temp;

GRANT EXECUTE ON FUNCTION screener_results(
    NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,
    BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT[],NUMERIC,INT,
    TEXT,BOOLEAN,INT,BOOLEAN
) TO anon, authenticated, service_role;
