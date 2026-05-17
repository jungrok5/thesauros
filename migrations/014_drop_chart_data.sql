-- 014_drop_chart_data.sql — drop precomputed chart cache
--
-- Replaced by on-demand SQL window functions in /api/chart. Saves
-- ~200MB once the chart cron is removed (Supabase free-tier budget).

DROP TABLE IF EXISTS chart_data;
