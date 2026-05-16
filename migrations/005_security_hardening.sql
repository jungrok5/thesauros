-- 005_security_hardening.sql — defense-in-depth on RLS + performance indexes
-- (folded together because both touch existing tables and we want a single
-- migration so reapplying from scratch ends in the same final state.)

-- ===========================================================================
-- 1. FORCE RLS on per-user tables
--    PostgreSQL by default lets the table OWNER (and superuser) bypass RLS.
--    `FORCE ROW LEVEL SECURITY` makes the policies apply even to the owner.
--    Combined with no superuser connections, this turns RLS into a real
--    last line of defense if the service_role key ever leaks.
-- ===========================================================================
ALTER TABLE users               FORCE ROW LEVEL SECURITY;
ALTER TABLE watchlist           FORCE ROW LEVEL SECURITY;
ALTER TABLE trade_log           FORCE ROW LEVEL SECURITY;
ALTER TABLE alerts              FORCE ROW LEVEL SECURITY;
ALTER TABLE alert_preferences   FORCE ROW LEVEL SECURITY;

-- (market-data tables stay non-forced — anon read is fine, writes are
--  service_role-only via the GitHub Actions batch jobs.)


-- ===========================================================================
-- 2. New performance indexes (perf review §3, §8, §11)
-- ===========================================================================

-- scan_results: hottest path is "is this ticker active right now?"
-- Existing idx_scan_ticker_date does NOT include is_active in its partial
-- expression. Add a partial index covering the common WHERE.
CREATE INDEX IF NOT EXISTS idx_scan_active_ticker
    ON scan_results (ticker) WHERE is_active = true;

-- alerts: telegram_worker._already_alerted asks (user_id, ticker,
-- alert_type) ordered DESC by created_at. The existing idx_alerts_user_unread
-- only covers unread; the alerted check needs a different shape.
CREATE INDEX IF NOT EXISTS idx_alerts_user_ticker_type_recent
    ON alerts (user_id, ticker, alert_type, created_at DESC);

-- watchlist: telegram_worker._watchlist_active filters by alerts_enabled.
CREATE INDEX IF NOT EXISTS idx_watchlist_user_alerts
    ON watchlist (user_id) WHERE alerts_enabled = true;
