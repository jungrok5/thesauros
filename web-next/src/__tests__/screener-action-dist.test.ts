/**
 * Lock down screener action distribution counting — the bug we're
 * guarding against:
 *
 *   value-classic preset returned 35 candidates, 24 of which had
 *   action=SELL_OR_SHORT (fundamentally cheap but chart broken).
 *   The page's original filter only counted AVOID + SELL, so those
 *   24 silently disappeared from the visible distribution. The user
 *   then read "통과 35" + "1위 메쎄이상" as if 1위 was 강매수,
 *   when the actual signal was HOLD + 24 of 35 in the avoid bucket.
 */
import { describe, it, expect } from "vitest";
import { actionDistribution } from "@/lib/screener-action-dist";

describe("actionDistribution", () => {
  it("buckets all 6 known actions correctly", () => {
    const out = actionDistribution([
      { action: "STRONG_BUY" },
      { action: "STRONG_BUY" },
      { action: "BUY" },
      { action: "HOLD" },
      { action: "HOLD" },
      { action: "AVOID" },
      { action: "SELL" },
      { action: "SELL_OR_SHORT" },
      { action: "SELL_OR_SHORT" },
      { action: null },
    ]);
    expect(out).toEqual({
      strong_buy: 2,
      buy: 1,
      hold: 2,
      avoid: 4,   // 1 AVOID + 1 SELL + 2 SELL_OR_SHORT
      none: 1,
    });
  });

  it("SELL_OR_SHORT does NOT silently disappear into 'none'", () => {
    // The original bug — SELL_OR_SHORT was the most common action in
    // the value-classic preset but the counter only checked AVOID + SELL.
    const out = actionDistribution([
      { action: "SELL_OR_SHORT" },
      { action: "SELL_OR_SHORT" },
    ]);
    expect(out.none).toBe(0);
    expect(out.avoid).toBe(2);
  });

  it("buckets the actual reproduction case (value-classic 35 rows)", () => {
    // Mirror real distribution seen on 2026-05-20:
    //   2 BUY, 8 HOLD, 24 SELL_OR_SHORT, 1 missing
    const rows: Array<{ action: string | null }> = [
      ...Array(2).fill({ action: "BUY" }),
      ...Array(8).fill({ action: "HOLD" }),
      ...Array(24).fill({ action: "SELL_OR_SHORT" }),
      { action: null },
    ];
    const out = actionDistribution(rows);
    expect(out.strong_buy).toBe(0);
    expect(out.buy).toBe(2);
    expect(out.hold).toBe(8);
    expect(out.avoid).toBe(24);
    expect(out.none).toBe(1);
    // Total must equal input length.
    const sum =
      out.strong_buy + out.buy + out.hold + out.avoid + out.none;
    expect(sum).toBe(rows.length);
  });

  it("empty input yields all zeros", () => {
    expect(actionDistribution([])).toEqual({
      strong_buy: 0,
      buy: 0,
      hold: 0,
      avoid: 0,
      none: 0,
    });
  });

  it("unknown action strings fall into 'none' (defensive)", () => {
    const out = actionDistribution([
      { action: "WEIRD_NEW_LABEL" },
    ]);
    expect(out.none).toBe(1);
  });
});
