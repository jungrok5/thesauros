-- 061 — Backfill `tickers.industry` from FDR KOSPI-DESC + KOSDAQ-DESC.
--
-- 2026-05-29 — screener was showing multiple same-industry hits at the
-- top because no sector-cap was applied; the backtest enforces
-- sector_cap=1/ISO-week/industry. To match, screener page needs the
-- ticker's industry. Only ~16% of tickers had `industry` filled
-- (mostly delistings or recently-listed entries). FDR's KOSPI-DESC +
-- KOSDAQ-DESC provide 2,605 of the ~2,700 active KR tickers with
-- 161 distinct industry categories.
--
-- The upload itself happens via app/db/backfill_tickers_industry.py
-- (which reads data/kr_sectors.csv and runs the same SET update). This
-- migration is the schema audit trail and the no-op idempotency guard.
-- Subsequent runs see the rows already populated and re-overwrite to
-- the current FDR snapshot (safe — industry classifications are stable).

-- No-op schema change (column exists since migration 002). The actual
-- value updates happen in app/db/backfill_tickers_industry.py.

COMMENT ON COLUMN tickers.industry IS
    'KR 종목 산업 분류 (FDR KOSPI-DESC + KOSDAQ-DESC, 161 카테고리). 사이트 스크리너 sector_cap=1/주/업종 분산 + 백테스트 sector_cap=1 일치 위해 backfill (migration 061, app/db/backfill_tickers_industry.py).';
