-- 004_rls.sql — Row Level Security
--
-- Service-role JWT bypasses RLS (used by Python backend + Next.js server actions).
-- Anon JWT (browser) is restricted to:
--   • public read on market data tables (tickers, scan_results, news, disclosures,
--     financials_eval, factors_eval, macro_state, bars_daily, health_ping).
--   • read/write on personal tables (users, watchlist, trade_log, alerts,
--     alert_preferences) only where auth.uid() = user_id.
--
-- For NextAuth-issued sessions to interoperate with Supabase RLS, we plan to set
-- a request claim ("user_id") on the supabase-js client per request from the
-- Next.js server using the service_role to issue per-user JWTs, OR query
-- through PostgREST with the service_role (server-side only) and apply
-- filters in our code. Either way, policies below enforce the database-level
-- guarantee.

-- Helper: turn the JWT 'sub' claim (set by Supabase Auth) into a UUID.
-- When called from server with service_role this returns NULL → bypass active.
CREATE OR REPLACE FUNCTION current_user_id() RETURNS UUID LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('request.jwt.claims', true)::jsonb->>'sub', '')::uuid;
$$;

-- ============================================================
-- ENABLE RLS  on all tables
-- ============================================================
ALTER TABLE users               ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickers             ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist           ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_log           ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_results        ENABLE ROW LEVEL SECURITY;
ALTER TABLE news                ENABLE ROW LEVEL SECURITY;
ALTER TABLE disclosures         ENABLE ROW LEVEL SECURITY;
ALTER TABLE financials_eval     ENABLE ROW LEVEL SECURITY;
ALTER TABLE factors_eval        ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts              ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_preferences   ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_state         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bars_daily          ENABLE ROW LEVEL SECURITY;
ALTER TABLE health_ping         ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- POLICIES — public read-only for market data
-- ============================================================
DROP POLICY IF EXISTS p_tickers_read ON tickers;
CREATE POLICY p_tickers_read ON tickers FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_scan_read ON scan_results;
CREATE POLICY p_scan_read ON scan_results FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_news_read ON news;
CREATE POLICY p_news_read ON news FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_disc_read ON disclosures;
CREATE POLICY p_disc_read ON disclosures FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_fin_read ON financials_eval;
CREATE POLICY p_fin_read ON financials_eval FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_fac_read ON factors_eval;
CREATE POLICY p_fac_read ON factors_eval FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_macro_read ON macro_state;
CREATE POLICY p_macro_read ON macro_state FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_bars_read ON bars_daily;
CREATE POLICY p_bars_read ON bars_daily FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS p_health_read ON health_ping;
CREATE POLICY p_health_read ON health_ping FOR SELECT TO anon, authenticated USING (true);

-- ============================================================
-- POLICIES — per-user tables (users / watchlist / trade_log / alerts / alert_preferences)
-- ============================================================

-- users: each row visible only to its owner (or via service_role)
DROP POLICY IF EXISTS p_users_self ON users;
CREATE POLICY p_users_self ON users FOR ALL TO authenticated
    USING  (id = current_user_id())
    WITH CHECK (id = current_user_id());

-- watchlist
DROP POLICY IF EXISTS p_watch_self ON watchlist;
CREATE POLICY p_watch_self ON watchlist FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

-- trade_log
DROP POLICY IF EXISTS p_trade_self ON trade_log;
CREATE POLICY p_trade_self ON trade_log FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

-- alerts
DROP POLICY IF EXISTS p_alerts_self ON alerts;
CREATE POLICY p_alerts_self ON alerts FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

-- alert_preferences
DROP POLICY IF EXISTS p_pref_self ON alert_preferences;
CREATE POLICY p_pref_self ON alert_preferences FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());
