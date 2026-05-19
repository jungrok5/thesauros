-- 023_company_profile.sql — company overview / sector / business
-- summary cache used by /stocks/[ticker] page header (Phase 3 of the
-- search-only pivot, 2026-05-19).
--
-- Source:
--   KR: DART company.json (company.dart.fss.or.kr) — corp_name, ceo,
--       est_dt, address, business overview (사업의 개요)
--   US: SEC EDGAR submissions.json + 10-K Item 1 (Business)
--
-- 1 row per ticker. Updated weekly via cron (sector / business doesn't
-- shift fast enough to justify daily fetches).

CREATE TABLE IF NOT EXISTS company_profile (
  ticker           text PRIMARY KEY,
  source           text NOT NULL,         -- 'DART' | 'SEC' | 'NAVER'
  -- Public-facing strings — already English/Korean from the source.
  industry         text,
  sectors          text[],
  summary          text,                  -- 1-3 paragraph business overview
  ceo              text,
  founded          date,
  hq               text,
  website          text,
  market_cap_krw   numeric,               -- KR-only (KRX cap); NULL for US
  market_cap_usd   numeric,               -- US-only (latest available)
  last_filings     jsonb,                 -- [{type, date, title, url}, ...] last ~10
  -- Update tracking
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_profile_updated_at
  ON company_profile (updated_at DESC);

ALTER TABLE company_profile ENABLE ROW LEVEL SECURITY;

-- Read-only for all authenticated users (no per-user data here, it's
-- a public company overview cache).
DROP POLICY IF EXISTS company_profile_read ON company_profile;
CREATE POLICY company_profile_read ON company_profile
  FOR SELECT
  TO authenticated
  USING (true);

-- Writes restricted to service role (cron). Same pattern as analyze_results.
DROP POLICY IF EXISTS company_profile_write ON company_profile;
CREATE POLICY company_profile_write ON company_profile
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
