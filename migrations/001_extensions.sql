-- 001_extensions.sql — enable required Postgres extensions
-- Idempotent: CREATE EXTENSION IF NOT EXISTS.

-- gen_random_uuid() etc.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Fuzzy text search for ticker / company-name autocomplete
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- (uuid-ossp is already enabled by Supabase default — keep harmless re-enable)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
