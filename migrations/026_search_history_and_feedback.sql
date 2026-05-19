-- 026 — search_history (per-user recent searches) + feedback (bug/feature reports)
--
-- search_history: shown on /stocks under "최근 검색"; trimmed to 30 newest
--   per user via AFTER INSERT trigger so the table never grows unbounded.
-- feedback: bug reports + feature suggestions submitted via /feedback,
--   triaged by admin via /admin/feedback. Resolved entries pruned after
--   90 days by app.db.retention.

-- ============================================================
-- search_history
-- ============================================================
CREATE TABLE IF NOT EXISTS search_history (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    ticker      VARCHAR(20),       -- resolved canonical ticker if user clicked through
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_search_history_user_recent
    ON search_history (user_id, created_at DESC);

-- Trim each user's history to the 30 newest rows on every insert. Pure
-- SQL, no app code needed — guarantees the table never balloons even if
-- a user runs hundreds of searches a day.
CREATE OR REPLACE FUNCTION trim_search_history() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM search_history
     WHERE user_id = NEW.user_id
       AND id NOT IN (
           SELECT id FROM search_history
            WHERE user_id = NEW.user_id
            ORDER BY created_at DESC
            LIMIT 30
       );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_trim_search_history ON search_history;
CREATE TRIGGER trg_trim_search_history
    AFTER INSERT ON search_history
    FOR EACH ROW EXECUTE FUNCTION trim_search_history();

-- RLS: only the owning user can read/write their history. Admin
-- service-key reads bypass RLS as usual.
ALTER TABLE search_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS search_history_owner ON search_history;
CREATE POLICY search_history_owner ON search_history
    FOR ALL TO authenticated
    USING (user_id::text = (current_setting('request.jwt.claim.sub', true))::text)
    WITH CHECK (user_id::text = (current_setting('request.jwt.claim.sub', true))::text);

-- ============================================================
-- feedback
-- ============================================================
CREATE TABLE IF NOT EXISTS feedback (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Denormalize email so a deleted user's ticket still has triage
    -- context for the admin.
    user_email   TEXT,
    category     VARCHAR(20) NOT NULL
                   CHECK (category IN ('bug', 'feature', 'other')),
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'in_progress', 'resolved', 'wont_fix')),
    admin_notes  TEXT,
    page_url     TEXT,         -- where the user was when they reported
    user_agent   TEXT,         -- light environment context for bugs
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_status_recent
    ON feedback (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_user
    ON feedback (user_id);

-- Auto-bump updated_at on UPDATE so admin status changes drive retention.
CREATE OR REPLACE FUNCTION touch_feedback_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_feedback_updated_at ON feedback;
CREATE TRIGGER trg_touch_feedback_updated_at
    BEFORE UPDATE ON feedback
    FOR EACH ROW EXECUTE FUNCTION touch_feedback_updated_at();

-- RLS: a user can create their own feedback + read their own threads;
-- everything else is service-key only (admin operations bypass RLS).
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS feedback_owner_read ON feedback;
CREATE POLICY feedback_owner_read ON feedback
    FOR SELECT TO authenticated
    USING (user_id::text = (current_setting('request.jwt.claim.sub', true))::text);
DROP POLICY IF EXISTS feedback_owner_insert ON feedback;
CREATE POLICY feedback_owner_insert ON feedback
    FOR INSERT TO authenticated
    WITH CHECK (user_id::text = (current_setting('request.jwt.claim.sub', true))::text);
