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

  it("L2 mid-cap sweet — same book_score, mid-cap beats microcap (2026-05-27)", () => {
    // Two OK rows, identical book_score, but A is microcap-floor (cap_q=0)
    // and B is at the tent peak (cap_q≈1). New ranking gives B a 0.2 bonus.
    const out = sortByBookSpirit([
      hit("MICRO.KQ", { book_score: 1.0, market_cap: 1e10 }),    // 100억 — below floor
      hit("MIDCAP.KS", { book_score: 1.0, market_cap: 5.48e11 }), // ~peak
    ]);
    expect(out.map((h) => h.ticker)).toEqual(["MIDCAP.KS", "MICRO.KQ"]);
  });

  it("L2 — lower book_score with mid-cap can still beat higher book with microcap", () => {
    // book 0.85 + cap 1.0 = 0.88 vs book 1.0 + cap 0 = 0.80 → mid-cap wins.
    const out = sortByBookSpirit([
      hit("HIGH_BOOK_MICRO.KQ", { book_score: 1.0, market_cap: 1e10 }),
      hit("MID_BOOK_MIDCAP.KS", { book_score: 0.85, market_cap: 5.48e11 }),
    ]);
    expect(out[0].ticker).toBe("MID_BOOK_MIDCAP.KS");
  });

  it("L2 — eligibility still trumps the L2 score (OK micro beats CONDITIONAL mid-cap)", () => {
    // Even if MICRO has worse L2 score, its OK grade ranks first.
    const out = sortByBookSpirit([
      hit("MID_COND.KQ", { book_score: 1.0, market_cap: 5.48e11, eligibility_grade: "CONDITIONAL" }),
      hit("OK_MICRO.KS", { book_score: 0.6, market_cap: 1e10, eligibility_grade: "OK" }),
    ]);
    expect(out[0].ticker).toBe("OK_MICRO.KS");
  });

  it("L2 — sort+slice(50) picks true top by L2 even when input > 50 (RPC limit-50 bug, 2026-05-27)", () => {
    // Regression: page.tsx originally called RPC with p_limit=50. When
    // ~177 rows saturate at book_score=1.0, the RPC's secondary sort
    // (ROE tiebreak) silently picks 50 candidates *before* the JS L2
    // sort ever sees the true winner. Dev-server dump (2026-05-27)
    // showed LX홀딩스 (L2=0.984) missing from the page, with
    // 인터로조 (L2=0.933) at rank 1. Fix: raise RPC limit + slice
    // top-50 in JS *after* L2 sort.
    //
    // This test pins the JS-side guarantee: given a pool > 50 with the
    // true L2 winner at position 60, sort+slice(50) must include it
    // and rank it first.
    const peak = 5.48e11; // tent peak
    const pool: SortableHit[] = [];
    // 55 OK-tier filler rows: same book=1.0, microcap (cap_q=0)
    for (let i = 0; i < 55; i++) {
      pool.push(hit(`F${i.toString().padStart(2, "0")}.KS`, {
        book_score: 1.0,
        market_cap: 1e10, // 100억 → cap_q=0 → L2=0.8
        roe: 0.1,
      }));
    }
    // The true L2 winner — placed at position 60 in input order.
    pool.push(hit("WINNER.KS", {
      book_score: 1.0,
      market_cap: peak,    // cap_q=1.0 → L2=1.0
      roe: 0.05,
    }));
    // 5 more filler rows.
    for (let i = 55; i < 60; i++) {
      pool.push(hit(`F${i.toString().padStart(2, "0")}.KS`, {
        book_score: 1.0,
        market_cap: 1e10,
        roe: 0.1,
      }));
    }
    const sortedTop50 = sortByBookSpirit(pool).slice(0, 50);
    expect(sortedTop50[0].ticker).toBe("WINNER.KS");
    expect(sortedTop50).toHaveLength(50);
  });
});
