/**
 * Regression suite for the freshness logic. Past bugs this guards:
 *
 *  - Using pattern.entry as the breakout reference produced
 *    runup = 0% for every completed pattern (entry is set to
 *    last_close at scan time), making YW/슈프리마/삼지전자 all show as
 *    "fresh #1" instead of the actual fresh tickers (국보디자인 etc).
 *
 *  - Reading lastClose from a paginated bars query (which silently
 *    capped at PostgREST's 1000-row default) gave a 5-year-old close
 *    for most tickers in a 50-row batch. We don't test that here
 *    directly — the fix is upstream — but the freshness function MUST
 *    yield deterministic results when given an explicit lastClose, so
 *    that an upstream test can simulate "correct" vs "wrong" lastClose
 *    and observe the divergence.
 *
 *  - Patterns without `extra.neckline / rim / ma_240 / ma_value` (e.g.,
 *    삼중바닥 only stores `bottoms`) must be skipped — including them
 *    via an `entry` fallback was the actual bug that put YW at #1.
 */
import { describe, it, expect } from "vitest";
import {
  breakoutLevel,
  bucketScore,
  compositeScore,
  freshnessMultiplier,
  pickFreshest,
  type FreshnessPatternInput,
} from "@/lib/freshness";

const yw_쌍바닥: FreshnessPatternInput = {
  completed: true,
  direction: "bullish",
  entry: 4695, // == last_close (this is the bug-inducing field)
  extra: { low1: { price: 2200 }, low2: { price: 2310 }, neckline: 4185 },
  kind: "쌍바닥",
};
const yw_삼중바닥_no_neckline: FreshnessPatternInput = {
  completed: true,
  direction: "bullish",
  entry: 4695,
  extra: { bottoms: [{}, {}, {}] }, // no neckline / rim / ma_*
  kind: "삼중바닥",
};
const sk_역HnS: FreshnessPatternInput = {
  completed: true,
  direction: "bullish",
  entry: 100500,
  extra: { neckline: 59100, head: {}, left_shoulder: {} },
  kind: "역H&S",
};
const fresh_쌍바닥_kbu: FreshnessPatternInput = {
  // 국보디자인 style: rcrum +3%
  completed: true,
  direction: "bullish",
  entry: 6900,
  extra: { neckline: 6700 },
  kind: "쌍바닥",
};

describe("bucketScore", () => {
  it("0-5% maps to bucket 0 (fresh)", () => {
    expect(bucketScore(0)).toBe(0);
    expect(bucketScore(2.5)).toBe(0);
    expect(bucketScore(4.99)).toBe(0);
  });
  it("5-15% maps to bucket 1 (chase-able)", () => {
    expect(bucketScore(5)).toBe(1);
    expect(bucketScore(12)).toBe(1);
    expect(bucketScore(14.99)).toBe(1);
  });
  it("15-30% maps to bucket 2 (partial entry gone)", () => {
    expect(bucketScore(15)).toBe(2);
    expect(bucketScore(29.99)).toBe(2);
  });
  it("-10..0% maps to bucket 3 (pullback)", () => {
    expect(bucketScore(-0.1)).toBe(3);
    expect(bucketScore(-9.99)).toBe(3);
  });
  it("<-10% maps to bucket 4 (broken)", () => {
    expect(bucketScore(-10.01)).toBe(4);
    expect(bucketScore(-50)).toBe(4);
  });
  it(">=30% maps to bucket 5 (stale)", () => {
    expect(bucketScore(30)).toBe(5);
    expect(bucketScore(70)).toBe(5);
    expect(bucketScore(450)).toBe(5);
  });
  it("orders sensibly: fresh < chase-able < partial < pullback < broken < stale", () => {
    expect(bucketScore(2)).toBeLessThan(bucketScore(10));
    expect(bucketScore(10)).toBeLessThan(bucketScore(20));
    expect(bucketScore(20)).toBeLessThan(bucketScore(-5));
    expect(bucketScore(-5)).toBeLessThan(bucketScore(-20));
    expect(bucketScore(-20)).toBeLessThan(bucketScore(70));
  });
});

describe("breakoutLevel", () => {
  it("prefers neckline when present", () => {
    expect(breakoutLevel(yw_쌍바닥)).toBe(4185);
  });
  it("returns null for patterns with only bottoms / no breakout key", () => {
    expect(breakoutLevel(yw_삼중바닥_no_neckline)).toBeNull();
  });
  it("never falls back to pattern.entry (that's the bug we're guarding)", () => {
    const p: FreshnessPatternInput = {
      completed: true,
      direction: "bullish",
      entry: 9999,
      extra: {},
      kind: "x",
    };
    expect(breakoutLevel(p)).toBeNull();
  });
  it("picks ma_240 for breakout-style patterns", () => {
    const p: FreshnessPatternInput = {
      completed: true,
      direction: "bullish",
      entry: 1000,
      extra: { ma_240: 800 },
      kind: "240MA 돌파매매",
    };
    expect(breakoutLevel(p)).toBe(800);
  });
});

describe("pickFreshest — actual recommendations bug scenario", () => {
  it("YW: 쌍바닥 with neckline 4185, last 4695 → bucket 1 (+12% 추격), NOT bucket 0", () => {
    const f = pickFreshest([yw_쌍바닥, yw_삼중바닥_no_neckline], 4695);
    expect(f).not.toBeNull();
    expect(f!.kind).toBe("쌍바닥");
    expect(f!.runupPct).toBeCloseTo(12.19, 1);
    expect(bucketScore(f!.runupPct)).toBe(1);
  });

  it("SK텔레콤 역H&S: bucket 5 (+70% long gone)", () => {
    const f = pickFreshest([sk_역HnS], 100500);
    expect(f).not.toBeNull();
    expect(bucketScore(f!.runupPct)).toBe(5);
  });

  it("Fresh ticker (~+3%) ranks BEFORE YW under bucket sort", () => {
    const ywFresh = pickFreshest([yw_쌍바닥], 4695);
    const kbuFresh = pickFreshest([fresh_쌍바닥_kbu], 6900);
    expect(ywFresh).not.toBeNull();
    expect(kbuFresh).not.toBeNull();
    expect(bucketScore(kbuFresh!.runupPct)).toBeLessThan(
      bucketScore(ywFresh!.runupPct),
    );
  });

  it("skips bearish patterns even when completed", () => {
    const bearish: FreshnessPatternInput = {
      completed: true, direction: "bearish",
      entry: 100, extra: { neckline: 80 }, kind: "쌍천장",
    };
    expect(pickFreshest([bearish], 100)).toBeNull();
  });

  it("skips incomplete patterns even when bullish", () => {
    const incomplete: FreshnessPatternInput = {
      completed: false, direction: "bullish",
      entry: 100, extra: { neckline: 80 }, kind: "쌍바닥",
    };
    expect(pickFreshest([incomplete], 100)).toBeNull();
  });

  it("returns null when no pattern has a usable breakout level", () => {
    expect(pickFreshest([yw_삼중바닥_no_neckline], 4695)).toBeNull();
  });
});

describe("freshnessMultiplier", () => {
  it("fresh patterns get full weight (1.0)", () => {
    expect(freshnessMultiplier(0)).toBe(1.0);
    expect(freshnessMultiplier(3)).toBe(1.0);
    expect(freshnessMultiplier(4.9)).toBe(1.0);
  });
  it("chase-able patterns get a moderate cut (0.65)", () => {
    expect(freshnessMultiplier(5)).toBe(0.65);
    expect(freshnessMultiplier(12)).toBe(0.65);
  });
  it("partial-gone patterns get a heavier cut (0.35)", () => {
    expect(freshnessMultiplier(20)).toBe(0.35);
  });
  it("pullback patterns get a moderate cut (0.55)", () => {
    expect(freshnessMultiplier(-5)).toBe(0.55);
  });
  it("broken patterns get crushed (0.1)", () => {
    expect(freshnessMultiplier(-30)).toBe(0.1);
  });
  it("stale patterns get crushed (0.05)", () => {
    expect(freshnessMultiplier(70)).toBe(0.05);
    expect(freshnessMultiplier(450)).toBe(0.05);
  });
  it("unknown freshness (no breakout info) gets 0.5 conservative penalty", () => {
    expect(freshnessMultiplier(null)).toBe(0.5);
  });
});

describe("compositeScore — best AND fresh, not just fresh", () => {
  it("strong + fresh ranks highest", () => {
    expect(compositeScore(0.91, 3)).toBeCloseTo(0.91, 2);
  });
  it("strong + stale gets crushed below moderate + fresh", () => {
    const sk = compositeScore(0.91, 70); // SK텔레콤 — strong but stale
    const fresh = compositeScore(0.85, 3); // medium strength but fresh
    expect(fresh).toBeGreaterThan(sk);
  });
  it("strong + chase still beats weak + fresh in most cases", () => {
    const yw = compositeScore(0.91, 12); // strong + chase = 0.59
    const weakFresh = compositeScore(0.5, 3); // weak + fresh = 0.5
    expect(yw).toBeGreaterThan(weakFresh);
  });
  it("국보디자인 vs YW vs SK텔레콤 ordering (the actual page case)", () => {
    const kbu = compositeScore(0.91, 3);     // 0.91
    const yw  = compositeScore(0.91, 12);    // 0.59
    const sk  = compositeScore(0.91, 70);    // 0.045
    expect(kbu).toBeGreaterThan(yw);
    expect(yw).toBeGreaterThan(sk);
  });
  it("action-only (no pattern freshness info) sits in the middle", () => {
    const actionOnly = compositeScore(0.91, null); // 0.455
    const fresh = compositeScore(0.91, 3);          // 0.91
    const stale = compositeScore(0.91, 70);         // 0.045
    expect(actionOnly).toBeLessThan(fresh);
    expect(actionOnly).toBeGreaterThan(stale);
  });
  it("monotonic in strength when freshness is held constant", () => {
    expect(compositeScore(0.9, 3)).toBeGreaterThan(compositeScore(0.8, 3));
    expect(compositeScore(0.8, 70)).toBeGreaterThan(compositeScore(0.7, 70));
  });
});
