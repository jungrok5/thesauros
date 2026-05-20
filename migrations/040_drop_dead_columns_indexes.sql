-- 040 — Phase 2: dead 컬럼 + unused 인덱스 정리
--
-- Pre-flight audit (2026-05-20) 로 확인된 NULL 100% 컬럼 + scan 0회
-- 인덱스. ALL NULL 이면 어차피 read 해도 의미 X, write 부담만.

-- factors_eval — 모든 percentile 컬럼 NULL (2745/2745)
-- 원래 미래에 종목별 백분위 채울 의도였으나 cron 안 채움. 사용도 X.
ALTER TABLE factors_eval
    DROP COLUMN IF EXISTS per_pctile,
    DROP COLUMN IF EXISTS pbr_pctile,
    DROP COLUMN IF EXISTS roe_pctile,
    DROP COLUMN IF EXISTS roa_pctile,
    DROP COLUMN IF EXISTS op_margin_pctile,
    DROP COLUMN IF EXISTS debt_ratio_pctile,
    DROP COLUMN IF EXISTS revenue_growth_pctile;

-- financials_eval — current_ratio / f_score NULL 100%
-- (Piotroski F-score 계산 안 됨, current_ratio 계산 안 됨)
ALTER TABLE financials_eval
    DROP COLUMN IF EXISTS current_ratio,
    DROP COLUMN IF EXISTS f_score;

-- company_profile — market_cap 컬럼 NULL 100%
-- DART 응답에 시총 안 들어옴. 시세 × 발행주식 별도 계산 필요한데 안 함.
ALTER TABLE company_profile
    DROP COLUMN IF EXISTS market_cap_krw,
    DROP COLUMN IF EXISTS market_cap_usd;

-- Unused 인덱스 — pg_stat_user_indexes 의 idx_scan = 0 인 것들
DROP INDEX IF EXISTS idx_institutional_ownership_holder;  -- 960KB, never scanned
DROP INDEX IF EXISTS idx_analyze_action;                  -- 72KB, action 은 JSONB 안에 (인덱스 못 씀)
DROP INDEX IF EXISTS idx_factors_passes_kang;             -- 32KB, value-classic preset 안 씀
DROP INDEX IF EXISTS idx_watchlist_user_alerts;           -- 16KB, alerts 별도 쿼리
DROP INDEX IF EXISTS idx_alerts_user_unread;              -- 16KB, 사용 안 함
DROP INDEX IF EXISTS idx_access_requests_decided_at;      -- 16KB
DROP INDEX IF EXISTS idx_market_warnings_level;           -- 8KB
