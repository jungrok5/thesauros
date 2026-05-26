/**
 * sortByBookSpirit — pins the 2026-05-26 reform: eligibility OK rows
 * outrank CONDITIONAL/WATCH/AVOID regardless of book_score, so a
 * top-1 ticker is always a safe buy candidate (the 339950.KQ vs
 * 003650.KS case that surfaced the bug).
 */
import { describe, it, expect } from "vitest";
import { sortByBookSpirit, type SortableHit } from "@/lib/screener-sort";

const hit = (
  ticker: string,
  overrides: Partial<SortableHit> = {},
): SortableHit => ({
  ticker,
  book_score: 1.0,
  roe: 0.1,
  catalyst_bars_since: null,
  eligibility_grade: "OK",
  ...overrides,
});

describe("sortByBookSpirit", () => {
  it("OK ranks above CONDITIONAL even when CONDITIONAL has higher book_score", () => {
    const out = sortByBookSpirit([
      hit("BAD.KQ", { book_score: 1.0, eligibility_grade: "CONDITIONAL", roe: 0.5 }),
      hit("GOOD.KS", { book_score: 0.85, eligibility_grade: "OK", roe: 0.1 }),
    ]);
    expect(out[0].ticker).toBe("GOOD.KS");
  });

  it("regression — 339950 vs 003650 (the bug that triggered the reform)", () => {
    // Same book_score 1.0, but 339950 is ambush CONDITIONAL and 003650 is OK.
    // Before reform: 339950 outranked 003650 via ROE tie-break.
    const out = sortByBookSpirit([
      hit("339950.KQ", { book_score: 1.0, eligibility_grade: "CONDITIONAL", roe: 0.18 }),
      hit("003650.KS", { book_score: 1.0, eligibility_grade: "OK", roe: 0.10 }),
    ]);
    expect(out[0].ticker).toBe("003650.KS");
    expect(out[1].ticker).toBe("339950.KQ");
  });

  it("within same grade, higher book_score wins", () => {
    const out = sortByBookSpirit([
      hit("A.KS", { book_score: 0.9 }),
      hit("B.KS", { book_score: 1.0 }),
    ]);
    expect(out.map((h) => h.ticker)).toEqual(["B.KS", "A.KS"]);
  });

  it("within same grade + book_score, fresher catalyst wins", () => {
    const out = sortByBookSpirit([
      hit("OLD.KS", { catalyst_bars_since: 8 }),
      hit("FRESH.KS", { catalyst_bars_since: 1 }),
      hit("NONE.KS", { catalyst_bars_since: null }),
    ]);
    expect(out.map((h) => h.ticker)).toEqual(["FRESH.KS", "OLD.KS", "NONE.KS"]);
  });

  it("final tie-break is ROE DESC then ticker ASC", () => {
    const out = sortByBookSpirit([
      hit("Z.KS", { roe: 0.05 }),
      hit("A.KS", { roe: 0.05 }),
      hit("M.KS", { roe: 0.20 }),
    ]);
    expect(out.map((h) => h.ticker)).toEqual(["M.KS", "A.KS", "Z.KS"]);
  });

  it("unknown grade ranks as OK (legacy rows not punished)", () => {
    const out = sortByBookSpirit([
      hit("LEGACY.KS", { book_score: 0.95, eligibility_grade: null }),
      hit("AVOID.KS", { book_score: 1.0, eligibility_grade: "AVOID" }),
    ]);
    expect(out[0].ticker).toBe("LEGACY.KS");
  });

  it("does not mutate the input array", () => {
    const input = [
      hit("X.KS", { eligibility_grade: "CONDITIONAL" }),
      hit("Y.KS", { eligibility_grade: "OK" }),
    ];
    const snapshot = input.map((h) => h.ticker);
    sortByBookSpirit(input);
    expect(input.map((h) => h.ticker)).toEqual(snapshot);
  });
});
