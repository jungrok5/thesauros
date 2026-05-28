-- 056 — analyze_results JSONB query path acceleration.
--
-- Problem (5-axis code review 2026-05-28):
-- screener_results RPC extracts (a.result ->> 'book_score')::NUMERIC
-- in WHERE/ORDER BY. With no index on the expression, every screener
-- page hit seq-scans factors_eval × analyze_results, casts JSONB per
-- row, then sorts. With ~2700 rows + p_limit=300 this is N×JSONB-cast
-- per request — main bottleneck identified.
--
-- Fix: expression indexes on the JSONB-extracted scalars the RPC uses.
-- Expression indexes are leaner than generated columns (no extra heap
-- bytes per row) and let the planner do an index-scan for the ORDER BY.
--
-- Three indexes:
--   1. (action) — for action_in filter (STRONG_BUY / BUY).
--   2. (book_score DESC) — for ORDER BY in screener_results.
--   3. (eligibility_grade) — for the /screener page's separate
--      eligibility re-fetch (currently a second .in() roundtrip).

-- Action filter (STRONG_BUY / BUY) — high-selectivity, used by every
-- screener page render via p_action_in.
CREATE INDEX IF NOT EXISTS idx_analyze_result_action
    ON analyze_results ((result ->> 'action'));

-- Book score sort — used by screener_results ORDER BY. NUMERIC cast
-- needed to preserve the planner's idea of an ORDER BY DESC.
CREATE INDEX IF NOT EXISTS idx_analyze_result_book_score
    ON analyze_results (((result ->> 'book_score')::NUMERIC) DESC NULLS LAST);

-- Eligibility grade — second-pass fetch on the screener page reads
-- only the eligibility subtree per ticker. Tiny cardinality (OK /
-- CONDITIONAL / WATCH / AVOID) so a hash index would be ideal, but
-- a regular btree partial index gets us most of the way.
CREATE INDEX IF NOT EXISTS idx_analyze_result_eligibility_grade
    ON analyze_results ((result -> 'eligibility' ->> 'grade'));
