/**
 * Phase mapping for NextDecisionChip — the key book-spirit invariant
 * surfaced by the chip (2026-05-26 site review M24):
 *
 *   wait    — Mon-Thu KST            (오늘은 관망)
 *   decide  — Fri pre-15:30 KST       (결정 시간)
 *   review  — Fri ≥15:30 + Sat + Sun  (결과 검토)
 *
 * Boundary tests around the Friday 15:30 cutoff because that's where
 * the book's "decision is settled" line gets drawn.
 */
import { describe, it, expect } from "vitest";
import { phaseFor } from "@/components/next-decision-chip";

// Helper: build a UTC Date that corresponds to a specific KST wall-clock.
// KST = UTC+9 → the UTC instant 9 hours earlier renders as that KST time.
function kst(yyyy: number, mm: number, dd: number, hh: number, min: number) {
  return new Date(Date.UTC(yyyy, mm - 1, dd, hh - 9, min, 0));
}

describe("NextDecisionChip phaseFor", () => {
  // 2026-05-25 is a Monday; 5/29 is Friday; 5/30 Sat; 5/31 Sun.
  it("Mon-Thu return 'wait'", () => {
    expect(phaseFor(kst(2026, 5, 25, 10, 0))).toBe("wait");   // Mon
    expect(phaseFor(kst(2026, 5, 26, 14, 30))).toBe("wait");  // Tue
    expect(phaseFor(kst(2026, 5, 27, 23, 59))).toBe("wait");  // Wed
    expect(phaseFor(kst(2026, 5, 28, 0, 0))).toBe("wait");    // Thu 00:00
    expect(phaseFor(kst(2026, 5, 28, 23, 59))).toBe("wait");  // Thu late
  });

  it("Fri before 15:30 KST returns 'decide'", () => {
    expect(phaseFor(kst(2026, 5, 29, 0, 0))).toBe("decide");
    expect(phaseFor(kst(2026, 5, 29, 9, 0))).toBe("decide");
    expect(phaseFor(kst(2026, 5, 29, 15, 0))).toBe("decide");
    expect(phaseFor(kst(2026, 5, 29, 15, 29))).toBe("decide");
  });

  it("Fri at exactly 15:30 KST flips to 'review' (close has happened)", () => {
    expect(phaseFor(kst(2026, 5, 29, 15, 30))).toBe("review");
    expect(phaseFor(kst(2026, 5, 29, 15, 31))).toBe("review");
    expect(phaseFor(kst(2026, 5, 29, 23, 59))).toBe("review");
  });

  it("Sat and Sun return 'review' (post-close, pre-next-week)", () => {
    expect(phaseFor(kst(2026, 5, 30, 9, 0))).toBe("review");   // Sat
    expect(phaseFor(kst(2026, 5, 31, 18, 0))).toBe("review");  // Sun
  });

  // Sun → Mon transition: at KST midnight Monday the chip must already
  // read 'wait' so the user opening their phone Monday morning sees
  // "관망" immediately, not the leftover weekend frame.
  it("Mon 00:00 KST is 'wait', not 'review'", () => {
    expect(phaseFor(kst(2026, 6, 1, 0, 0))).toBe("wait");
  });
});
