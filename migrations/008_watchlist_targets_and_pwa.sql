-- 008_watchlist_targets_and_pwa.sql — price targets + PWA push subs

-- Watchlist: target price / target % alerts
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS target_price NUMERIC;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS target_pct_from_entry NUMERIC;   -- e.g. 0.10 = +10%
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS stop_price NUMERIC;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS stop_pct_from_entry NUMERIC;     -- e.g. -0.05 = -5%
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS target_hit_at TIMESTAMPTZ;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS stop_hit_at TIMESTAMPTZ;

-- PWA web-push subscriptions (one user can have multiple devices)
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions (user_id);

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE push_subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_push_self ON push_subscriptions;
CREATE POLICY p_push_self ON push_subscriptions FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

-- Self-link tokens (user creates this string on Settings, pastes to bot)
CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    token VARCHAR(48) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '1 hour',
    consumed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tg_tokens_user ON telegram_link_tokens (user_id);

ALTER TABLE telegram_link_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_link_tokens FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tg_self ON telegram_link_tokens;
CREATE POLICY p_tg_self ON telegram_link_tokens FOR ALL TO authenticated
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());
