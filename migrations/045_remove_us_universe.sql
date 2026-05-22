-- 045 — Remove US equity universe (책 정신 + 운영 단순화)
--
-- 책 2부 7장 탑다운: 코스피/코스닥 종목 매매 + 미국은 글로벌 지수
-- (탑다운 1단계) 로만 활용. 종목 매매는 KR. 또 Naver/yfinance 둘 다
-- GH Actions Azure IP 차단 (project_us_yfinance_blocked.md 참조) 으로
-- US 종목 자동 분석은 사실상 불가능 — 매 cron 마다 헛도는 코드가 많음.
-- 차트 이미지 분석 기능 (P_VISION) 으로 대체.
--
-- 영향:
--   1. tickers.market IN ('NASDAQ','NYSE','AMEX','ARCA','BATS')
--      → is_active = false. Master row 는 보존 (사용자 watchlist 참조).
--   2. US bars 행 즉시 삭제 — DB 공간 회복 (~10MB 예상).
--   3. US analyze_results 행 즉시 삭제 — eligibility/action 표시 X.
--   4. watchlist 행은 보존 — UI 가 "분석 중단" 안내로 graceful 표시.

-- ── 1. tickers 비활성화 ──────────────────────────────────────────────
UPDATE tickers
   SET is_active = false
 WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS');

-- ── 2. bars 삭제 ────────────────────────────────────────────────────
DELETE FROM bars
 WHERE ticker IN (
   SELECT ticker FROM tickers
    WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')
 );

-- ── 3. analyze_results 삭제 ─────────────────────────────────────────
DELETE FROM analyze_results
 WHERE ticker IN (
   SELECT ticker FROM tickers
    WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')
 );

-- ── 4. scan_results 삭제 (active 신호 까지 함께) ──────────────────
DELETE FROM scan_results
 WHERE ticker IN (
   SELECT ticker FROM tickers
    WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')
 );

-- ── 5. fundamentals / disclosures (있다면) 삭제 ─────────────────────
DELETE FROM fundamentals
 WHERE ticker IN (
   SELECT ticker FROM tickers
    WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')
 );

DELETE FROM disclosures
 WHERE ticker IN (
   SELECT ticker FROM tickers
    WHERE market IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')
 );

-- ── 6. VACUUM 으로 disk 회복 (postgres autovacuum 보다 즉시) ─────────
-- VACUUM 은 transaction 밖에서만 가능 — 별도 connection 으로 실행해야
-- 함. migration runner 가 처리. 여기서는 DELETE 만.

COMMENT ON TABLE tickers IS
  '종목 master. KOSPI/KOSDAQ active. US (NASDAQ/NYSE/AMEX/ARCA/BATS) '
  ' deactivated 2026-05-22 — 책 정신 + Naver/yfinance cloud-IP 차단 + '
  '차트 이미지 분석으로 대체.';
