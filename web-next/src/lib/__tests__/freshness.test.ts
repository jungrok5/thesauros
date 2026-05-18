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
