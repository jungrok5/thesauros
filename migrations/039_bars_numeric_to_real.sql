-- 039 — bars NUMERIC → REAL : 60+ MB 절약
--
-- 사용자 계획 (2026-05-20): \"데이터 타입 줄이고...\" — 240MA backfill
-- 위한 공간 확보 + 압축 계획 Phase 1.
--
-- 현재: bars.open/high/low/close 가 NUMERIC (no precision)
--       = 16-24 bytes per value
-- 변경: REAL (float4) = 4 bytes per value
-- 797K rows × 4 cols × ~20 bytes = 64 MB → 16 MB = -48 MB
--
-- 정밀도 검증:
--   - 한국 주식: 원 단위 정수 (예: 75,900). REAL = 7 digit ~ float32
--     의 precision = max ~16,777,216 (2^24). 한국 종목 5자리 가격이라
--     overflow 없음.
--   - 미국 주식: 소수 가능 (예: $245.67). REAL 4-7 digit precision
--     충분.
--   - 시총 5천억 같은 큰 값은 bars 에 없음 (그건 별도 시총 필드).
--
-- 다운타임: 약 5-10분 (ALTER TABLE 이 테이블 rewrite).
-- volume 은 BIGINT 그대로 유지 (정수, 메모리 8 bytes).

ALTER TABLE bars
    ALTER COLUMN open  TYPE REAL USING open::REAL,
    ALTER COLUMN high  TYPE REAL USING high::REAL,
    ALTER COLUMN low   TYPE REAL USING low::REAL,
    ALTER COLUMN close TYPE REAL USING close::REAL;
