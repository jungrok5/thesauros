/**
 * book-spirit-ranking — pins the L2 mid-cap sweet formula picked from
 * the 2026-05-27 14-variant grid (CAGR +20.65% / DD 37.3% / Calmar 0.55).
 *
 * Guard against:
 *  • Threshold drift — changing CAP_LOW / CAP_HIGH / peak silently
 *    moves the entire screener ranking. Pin the math.
 *  • Null cap regression — backfill is one-shot; until ingest_factors
 *    re-runs the column may be null on some rows. Score must degrade
 *    to 0.8 × book_score, not NaN / undefined.
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

describe("bookSpiritScore", () => {
  it("with null cap, score = BOOK_WEIGHT × book (graceful pre-backfill)", () => {
    expect(bookSpiritScore(1.0, null)).toBeCloseTo(BOOK_WEIGHT, 6);
    expect(bookSpiritScore(0.5, null)).toBeCloseTo(BOOK_WEIGHT * 0.5, 6);
  });

  it("at peak cap with book=1, returns BOOK_WEIGHT + CAP_WEIGHT = 1", () => {
    const peak = Math.sqrt(3e11 * 1e12);
    expect(bookSpiritScore(1.0, peak)).toBeCloseTo(1.0, 6);
  });

  it("same book, mid-cap beats microcap and megacap", () => {
    const micro = bookSpiritScore(1.0, 3e10);     // 300억 — below floor
    const mid   = bookSpiritScore(1.0, 5.5e11);   // ~peak
    const mega  = bookSpiritScore(1.0, 5e13);     // 50조 — above ceiling
    expect(mid).toBeGreaterThan(micro);
    expect(mid).toBeGreaterThan(mega);
    expect(micro).toBe(BOOK_WEIGHT); // both zeros on cap_q
    expect(mega).toBe(BOOK_WEIGHT);
  });

  it("weights sum to 1.0", () => {
    expect(BOOK_WEIGHT + CAP_WEIGHT).toBeCloseTo(1.0, 6);
  });

  it("null book_score falls back to 0 (not NaN)", () => {
    const peak = Math.sqrt(3e11 * 1e12);
    expect(bookSpiritScore(null, peak)).toBeCloseTo(CAP_WEIGHT, 6);
    expect(bookSpiritScore(undefined, null)).toBe(0);
  });
});
