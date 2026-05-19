-- 025_drop_bars_daily.sql — drop the obsolete daily-bar table.
--
-- Migration 021 (weekly pivot) introduced `bars` with granularity in
-- ('W','M') and stopped writing to `bars_daily`. The site has been
-- weekly-only for months but the table sat around without a writer.
--
-- The two remaining consumers (/api/quote, <LastClose>) were just
-- repointed at `bars` granularity='W' in the same commit that adds
-- this migration. Verify no callers reference `bars_daily` before
-- applying:
--   rg -n "bars_daily" web-next/src/ app/   → returns nothing
--
-- Frees up index space + the table itself. Run AFTER deploying the
-- code that doesn't read it (otherwise /api/quote 500s for a minute).

DROP TABLE IF EXISTS bars_daily CASCADE;
