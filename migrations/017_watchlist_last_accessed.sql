-- 017_watchlist_last_accessed.sql — TTL anchor for observing entries.
--
-- Stock detail page renders touch this column when the signed-in user
-- viewed a ticker they already watchlisted. Retention then purges
-- `category = 'observing'` rows that haven't been touched in 90 days.
-- `holding` rows are exempt (user has money in them).

ALTER TABLE watchlist
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill existing rows to created_at so old watchlist entries don't
-- get insta-purged on the next retention run.
UPDATE watchlist
   SET last_accessed_at = COALESCE(last_accessed_at, created_at, now())
 WHERE last_accessed_at IS NULL OR last_accessed_at = '1970-01-01'::timestamptz;
