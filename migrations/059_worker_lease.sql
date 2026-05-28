-- 059 — worker_lease: pool-safe alternative to session-scoped advisory locks.
--
-- 2026-05-28 incident: telegram_worker used pg_try_advisory_lock(BIGINT)
-- to dedup concurrent dispatches. On Supabase's Supavisor pooler the
-- session lifetime is decoupled from the client connection — when a
-- worker's psycopg conn returns to the pool, Supavisor may NOT close
-- the upstream Postgres session. The advisory lock (session-scoped)
-- therefore stays held until the upstream session is eventually
-- recycled, by which time minutes/hours of subsequent worker runs have
-- all returned `false` on `pg_try_advisory_lock` and silently no-op'd.
--
-- Fix: switch to a row-based lease with explicit TTL. Atomic acquisition
-- via INSERT ... ON CONFLICT DO UPDATE WHERE expired. Works regardless
-- of pooling; auto-recovers from crashed workers when the TTL expires.

CREATE TABLE IF NOT EXISTS worker_lease (
    name        TEXT        PRIMARY KEY,           -- e.g. 'telegram_worker'
    holder_id   TEXT        NOT NULL,              -- random UUID per acquisition
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

-- Internal worker coordination — never user-readable. Service role only.
ALTER TABLE worker_lease ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_lease FORCE ROW LEVEL SECURITY;
-- No SELECT/INSERT/UPDATE/DELETE policies for authenticated → only the
-- service-role bypass can touch it.

COMMENT ON TABLE worker_lease IS
    'Pool-safe distributed lock. Each worker writes name + UUID + TTL via INSERT ... ON CONFLICT WHERE expired. Auto-released by TTL on crash. Replaces pg_try_advisory_lock (Supavisor pool-unsafe — see 2026-05-28 incident notes in telegram_worker.py).';
