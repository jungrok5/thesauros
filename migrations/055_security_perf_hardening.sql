-- 055 — 2026-05-28 security + perf hardening from 5-axis code review.
--
-- A. RLS policy fix for stop_loss_alert_seen (migration 049 used
--    `current_user` = Postgres role name, NOT the auth UUID, so the
--    authenticated path was always-false). Replace with current_user_id().
-- B. Add SET search_path = public, pg_temp to every RPC defined in
--    033/034/037/042/043/053 — Supabase advisor flag, blocks
--    search-path hijacking even though current functions only touch
--    public schema.
-- C. Index for retention DELETE on alerts(created_at) — current daily
--    DELETE WHERE created_at < ... had to seq-scan the whole table.

-- ──────────────────────────────────────────────────────────────────
-- A. stop_loss_alert_seen RLS policy fix
-- ──────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS sl_alert_seen_read ON stop_loss_alert_seen;
CREATE POLICY sl_alert_seen_read ON stop_loss_alert_seen
    FOR SELECT TO authenticated
    USING (user_id = current_user_id());

-- ──────────────────────────────────────────────────────────────────
-- B. Lock down RPC search_path so any future schema games can't
--    redirect referenced tables. All are SQL functions (no plpgsql)
--    that only read public tables; safe to pin search_path explicitly.
-- ──────────────────────────────────────────────────────────────────
ALTER FUNCTION screener_results(
    NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC,
    BOOLEAN, BOOLEAN, BOOLEAN, BOOLEAN, TEXT, TEXT[], NUMERIC, INT,
    TEXT, BOOLEAN, INT
) SET search_path = public, pg_temp;

ALTER FUNCTION screener_action_distribution(
    NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC,
    BOOLEAN, BOOLEAN, BOOLEAN, BOOLEAN
) SET search_path = public, pg_temp;

ALTER FUNCTION volume_surge_for_ticker(VARCHAR)
    SET search_path = public, pg_temp;

-- decide_access_request is SECURITY DEFINER so already needs the
-- search_path hardening — explicitly set it.
ALTER FUNCTION decide_access_request(UUID, TEXT, UUID, TEXT)
    SET search_path = public, pg_temp;

ALTER FUNCTION current_user_id()
    SET search_path = public, pg_temp;

-- ──────────────────────────────────────────────────────────────────
-- C. Index for the retention DELETE path on alerts.
--    Existing indexes lead with user_id; the daily cleanup
--    `WHERE created_at < CURRENT_DATE - 60 days` can't use them and
--    seq-scans alerts every cron. A small partial index on created_at
--    alone is enough — DELETE only needs to find rows older than the
--    cutoff, not which user owns them.
-- ──────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_alerts_created_at
    ON alerts (created_at);
