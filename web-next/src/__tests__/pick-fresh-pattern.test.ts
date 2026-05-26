/**
 * Pin the 2026-05-26 fix: pickFreshBullishPattern must honor the
 * analyzer's entry_plan.based_on (book-spirit weekly-first pick).
 *
 * Pre-fix: the BookVerdict headline narrated "삼중바닥 패턴 완성"
 * while the entry_plan that filled entry/stop/target came from
 * "장대양봉 catalyst (weekly)" — two different patterns surfacing
 * in the same card. Confused users.
 */
import { describe, it, expect } from "vitest";
import { pickFreshBullishPattern } from "@/components/book-verdict";
import type { AnalysisResult, Pattern } from "@/lib/types/analysis";

function pat(overrides: Partial<Pattern>): Pattern {
  return {
    kind: "쌍바닥",
    direction: "bullish",
    confidence: 0.8,
    completed: true,
    detected_at: "2026-05-22",
    entry: 100,
    stop: 90,
    target: 120,
    reason: "",
    timeframe: "weekly",
    extra: { neckline: 100 },
    ...overrides,
  };
}

function result(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    ticker: "TEST.KS",
    as_of: "2026-05-22",
    last_close: 110,
    rows: 260,
    action: "STRONG_BUY",
    book_score: 1.0,
    book_score_components: {},
    trend: {},
    last_candle: null,
    patterns: [],
    reversals: [],
    volume_case: null,
    entry_plan: null,
    ...overrides,
  } as AnalysisResult;
}

describe("pickFreshBullishPattern", () => {
  it("honors entry_plan.based_on when set (2026-05-26 fix)", () => {
    // 000370 case: backend's entry_plan picked the catalyst, frontend
    // used to pick 삼중바닥. Now must agree.
    const r = result({
      last_close: 7150,
      patterns: [
        pat({ kind: "삼중바닥", timeframe: "weekly",
              extra: { neckline: 7000 } }),
        pat({ kind: "장대양봉 catalyst", timeframe: "weekly",
              extra: { catalyst_high: 7100 } }),
      ],
      entry_plan: {
        entry: 7190, stop: 6650, target: 8630,
        based_on: "장대양봉 catalyst (weekly)",
      },
    });
    const out = pickFreshBullishPattern(r);
    expect(out?.kind).toBe("장대양봉 catalyst");
  });

  it("matches by timeframe too — weekly vs monthly same-kind pair", () => {
    const r = result({
      last_close: 110,
      patterns: [
        pat({ kind: "삼중바닥", timeframe: "monthly",
              extra: { neckline: 95 } }),
        pat({ kind: "삼중바닥", timeframe: "weekly",
              extra: { neckline: 100 } }),
      ],
      entry_plan: {
        entry: 110, stop: 99, target: 130,
        based_on: "삼중바닥 (weekly)",
      },
    });
    const out = pickFreshBullishPattern(r);
    expect(out?.kind).toBe("삼중바닥");
    expect(out?.breakout).toBe(100);   // weekly's neckline, not monthly's 95
  });

  it("falls back to runup-closest heuristic when entry_plan is null", () => {
    const r = result({
      last_close: 110,
      patterns: [
        pat({ kind: "쌍바닥", timeframe: "weekly",
              extra: { neckline: 105 } }),
        pat({ kind: "역H&S",  timeframe: "weekly",
              extra: { neckline: 109 } }),
      ],
      entry_plan: null,
    });
    const out = pickFreshBullishPattern(r);
    // legacy "smallest runup" wins: 역H&S has 109 (closer to 110)
    expect(out?.kind).toBe("역H&S");
  });

  it("falls back when entry_plan's based_on pattern is missing in patterns array", () => {
    const r = result({
      last_close: 110,
      patterns: [
        pat({ kind: "쌍바닥", extra: { neckline: 105 } }),
      ],
      entry_plan: {
        entry: 110, stop: 100, target: 130,
        based_on: "장대양봉 catalyst (weekly)",   // not in patterns
      },
    });
    const out = pickFreshBullishPattern(r);
    expect(out?.kind).toBe("쌍바닥");
  });

  it("skips invalidated/below-breakout pattern even when entry_plan names it", () => {
    const r = result({
      last_close: 100,                 // below the 105 breakout
      patterns: [
        pat({ kind: "쌍바닥", extra: { neckline: 105 } }),
      ],
      entry_plan: {
        entry: 100, stop: 90, target: 130,
        based_on: "쌍바닥 (weekly)",
      },
    });
    const out = pickFreshBullishPattern(r);
    expect(out).toBeNull();
  });
});
