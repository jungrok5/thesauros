/**
 * book-spirit-ranking — honest spec after 2026-05-29 Phase 9 PIT audit.
 *
 * The prior L2 formula (0.8×book + 0.2×cap_q) was retired when point-
 * in-time cap re-tests showed the cap_q contribution was a look-ahead
 * artifact (CAGR collapsed +20.65 → +8.07 under PIT). Honest score is
 * book_score alone; the capQuality tent is retained for diagnostic
 * display but CAP_WEIGHT is 0.
 *
 * Guard against:
 *  • Re-introducing CAP_WEIGHT > 0 without an explicit PIT-valid
 *    justification.
 *  • Null book_score regression (must degrade to 0, not NaN).
 *  • capQuality threshold drift — preserved for sites that still
 *    render mid-cap context tooltips.
 */
import { describe, it, expect } from "vitest";
import {
  capQuality,
  bookSpiritScore,
  BOOK_WEIGHT,
  CAP_WEIGHT,
} from "@/lib/book-spirit-ranking";

describe("capQuality (tent shape on log10 cap)", () => {
  it("returns 0 below 500억 floor (microcap exclusion)", () => {
    expect(capQuality(1e9)).toBe(0);       // 10억
    expect(capQuality(4.99e10)).toBe(0);   // 499억
    expect(capQuality(5e10)).toBe(0);      // 500억 — boundary excluded
  });

  it("returns 0 above 10조 ceiling (mega-cap exclusion)", () => {
    expect(capQuality(1e13)).toBe(0);      // 10조 — boundary excluded
    expect(capQuality(2e15)).toBe(0);      // Samsung-scale
  });

  it("peaks at ~5,480억 KRW (sqrt of 3000억 × 1조)", () => {
    // The tent peak sits at the geometric midpoint between the mid-cap
    // band edges. log10 of 5.48e11 ≈ 11.738 — pin to 4 digits.
    const peak = Math.sqrt(3e11 * 1e12); // 5.477e11
    expect(capQuality(peak)).toBeCloseTo(1.0, 6);
  });

  it("interpolates linearly on log10 between floor and peak", () => {
    // log10(5e10) = 10.699, log10(peak) ≈ 11.738 → span 1.039.
    // A cap at log10 = 11.218 (halfway) should give q ≈ 0.5.
    const halfway = Math.pow(10, (Math.log10(5e10) + 11.7385876) / 2);
    expect(capQuality(halfway)).toBeCloseTo(0.5, 2);
  });

  it("interpolates linearly on log10 between peak and ceiling", () => {
    // log10(peak) ≈ 11.738, log10(1e13) = 13 → span 1.262.
    // Cap at log10 = 12.369 (halfway) should give q ≈ 0.5.
    const halfway = Math.pow(10, (11.7385876 + 13) / 2);
    expect(capQuality(halfway)).toBeCloseTo(0.5, 2);
  });

  it("null / undefined / non-positive cap → 0 (degrades gracefully)", () => {
    expect(capQuality(null)).toBe(0);
    expect(capQuality(undefined)).toBe(0);
    expect(capQuality(0)).toBe(0);
    expect(capQuality(-1)).toBe(0);
  });
});

describe("bookSpiritScore (honest spec — book-only after PIT audit)", () => {
  it("returns book_score directly when book_weight=1.0", () => {
    expect(bookSpiritScore(1.0, null)).toBeCloseTo(1.0, 6);
    expect(bookSpiritScore(0.5, null)).toBeCloseTo(0.5, 6);
  });

  it("cap argument is ignored (CAP_WEIGHT=0 after PIT audit)", () => {
    const peak = Math.sqrt(3e11 * 1e12);
    expect(bookSpiritScore(0.7, peak)).toBeCloseTo(0.7, 6);
    expect(bookSpiritScore(0.7, 1e10)).toBeCloseTo(0.7, 6);
    expect(bookSpiritScore(0.7, 5e13)).toBeCloseTo(0.7, 6);
  });

  it("weights remain in [0, 1] with book_weight=1, cap_weight=0", () => {
    expect(BOOK_WEIGHT).toBe(1.0);
    expect(CAP_WEIGHT).toBe(0.0);
  });

  it("null/undefined book_score falls back to 0 (not NaN)", () => {
    expect(bookSpiritScore(null, null)).toBe(0);
    expect(bookSpiritScore(undefined, null)).toBe(0);
    expect(bookSpiritScore(null, 5.5e11)).toBe(0);
  });

  it("regression guard: do NOT re-introduce CAP_WEIGHT > 0 without PIT proof", () => {
    // The 2026-05-27 → 2026-05-29 chapter proved CAP_WEIGHT>0 against a
    // today-snapshot cap inflates backtest CAGR by ~+12 pp via
    // look-ahead. If someone reintroduces cap weighting, this test
    // forces them to update the proof trail in book-spirit-ranking.ts.
    expect(CAP_WEIGHT).toBe(0.0);
  });
});
