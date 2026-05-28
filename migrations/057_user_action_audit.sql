-- 057 — append-only audit log for user-initiated destructive ops.
--
-- Why: 5-axis code review (2026-05-28) flagged that DELETE /api/watchlist,
-- DELETE /api/watchlist-groups, DELETE /api/search-history, and admin
-- PATCH /api/admin/feedback/[id] have no audit trail. A compromised
-- session can purge data without trace. This is the minimum-viable
-- ledger.
--
-- Append-only by RLS — no UPDATE / DELETE policy means even the user
-- can't tamper with history. Service-role inserts only (writes are
-- triggered by trusted server-side route handlers).

CREATE TABLE IF NOT EXISTS user_action_audit (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE NO ACTION,
    action TEXT NOT NULL,          -- e.g. "watchlist.delete", "feedback.admin_patch"
    target_kind TEXT,              -- e.g. "ticker", "feedback_id", "group_id"
    target_id TEXT,                -- string-cast id of the affected entity
    payload JSONB,                 -- additional context (before/after diff, IP, etc)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_action_audit_user_time
    ON user_action_audit (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_action_audit_action
    ON user_action_audit (action, created_at DESC);

-- RLS — append-only. Authenticated users can read their OWN history;
-- service role inserts; no policy for UPDATE/DELETE.
ALTER TABLE user_action_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_action_audit FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_read_self ON user_action_audit;
CREATE POLICY audit_read_self ON user_action_audit
    FOR SELECT TO authenticated
    USING (user_id = current_user_id());

COMMENT ON TABLE user_action_audit IS
    'Append-only audit ledger of user-initiated destructive ops. Inserts via service role only; users may read their own history. No UPDATE/DELETE policies (history is immutable).';
