-- 009_admin_and_access.sql — admin roles + access request workflow
--
-- Replaces the old env-based AUTH_ALLOWED_EMAILS whitelist with a DB-backed
-- model: every signed-in user gets a `users` row, but only those with
-- access_status='approved' can use the app. New users land on /pending,
-- can submit a request, and an admin (role='admin') approves them from
-- /admin/access. The first admin is bootstrapped from env ADMIN_EMAILS
-- on first login.

-- ---- 1. roles + access status on users -----------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'user';
    -- 'user' | 'admin'
ALTER TABLE users ADD COLUMN IF NOT EXISTS access_status VARCHAR(16) NOT NULL DEFAULT 'pending';
    -- 'pending' | 'approved' | 'rejected'
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_access_status ON users (access_status);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);

-- ---- 2. telegram_chat_id UNIQUE ------------------------------------
-- Prevent one telegram account from being silently bound to multiple
-- web accounts (would leak alerts across users).
-- Partial unique so multiple NULLs are allowed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_chat_id
    ON users (telegram_chat_id)
    WHERE telegram_chat_id IS NOT NULL;

-- ---- 3. access_requests --------------------------------------------
-- One row per user; updated in place when the user re-submits.
CREATE TABLE IF NOT EXISTS access_requests (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT,                              -- user-supplied justification
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ,
    decided_by UUID REFERENCES users(id),
    decision VARCHAR(16),                     -- 'approved' | 'rejected'
    note TEXT                                  -- admin's note (optional)
);
CREATE INDEX IF NOT EXISTS idx_access_requests_decided_at
    ON access_requests (decided_at NULLS FIRST);

ALTER TABLE access_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_access_req_self ON access_requests;
CREATE POLICY p_access_req_self ON access_requests FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());
