-- 022_drop_themes.sql — drop theme tables.
--
-- The /themes page (and /themes/[id]) is removed in the search-only
-- pivot (2026-05-19). Universe-wide auto-classification produced too
-- many false positives (LG우, GOOGL pre-stretch-gate, etc.). Site now
-- centres on user search + on-demand analysis per ticker, so the
-- theme heatmap data has no consumer left.
--
-- CASCADE drops the per-table RLS policies + indexes together.

DROP TABLE IF EXISTS theme_daily CASCADE;
DROP TABLE IF EXISTS theme_members CASCADE;
DROP TABLE IF EXISTS themes CASCADE;
