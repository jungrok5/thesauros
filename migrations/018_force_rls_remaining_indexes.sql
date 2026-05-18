-- 018_force_rls_remaining_indexes.sql
--
-- 1) FORCE RLS on the remaining per-user tables. 005 covered the five
--    obvious ones (users / watchlist / trade_log / alerts /
--    alert_preferences). These three were missed at the time:
--      - access_requests          (per-user, with a decided_by FK)
--      - telegram_link_tokens     (one row per pending link)
--      - push_subscriptions       (browser push endpoints)
--    Without FORCE, a leaked service-role key bypasses RLS and exposes
--    per-user rows. With FORCE the policies apply universally.
--
-- 2) Composite index supporting /recommendations' hot filter:
--      WHERE is_active = true AND strength >= 0.7 ORDER BY strength DESC
--    The existing 005 partial index covers (ticker) on the active set;
--    this one covers (strength DESC) on the active set so the planner
--    can skip the post-filter sort.

ALTER TABLE access_requests       FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_link_tokens  FORCE ROW LEVEL SECURITY;
ALTER TABLE push_subscriptions    FORCE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_scan_active_strength_desc
    ON scan_results (strength DESC)
 WHERE is_active = true;
