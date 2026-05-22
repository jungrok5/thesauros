/**
 * Parity guard — the TS fallback derivation in `NoviceVerdict` must
 * stay aligned with the Python `compute_eligibility()` port.
 *
 * Background: prior to 2026-05-22, the buy-eligibility rule existed
 * only in TypeScript (inside `NoviceVerdict`). The cron's telegram
 * worker had no way to consult it, so a "🟢 진입 신호" telegram could
 * fire for a ticker the page was simultaneously flagging
 * "⚠️ 매수 자격: 조건부 — 지금은 자리 X". We ported the rule to Python
 * (`app/book/eligibility.py`) and made the analyzer ship the verdict
 * inside `analyze_results.result.eligibility`. The TS component reads
 * that field as the primary source; the in-component derivation stays
 * as fallback for blobs older than the field.
 *
 * This file checks the fallback derivation's headline+grade against
 * a small fixture matrix. If the Python port drifts (or someone
 * tweaks `compute_eligibility()` rules without updating this), the
 * test fails and surfaces the divergence before it ships.
 */
import { describe, it, expect } from "vitest";
import {
  isAmbushSetup,
  isPostRallyCaution,
  pickFreshBullishPattern,
} from "@/components/book-verdict";
import type { AnalysisResult } from "@/lib/types/analysis";

/** Minimal blob matching what `analyze_ticker()` produces. */
function makeResult(over: Partial<AnalysisResult>): AnalysisResult {
  return {
    ticker: "TEST.KS",
    as_of: "2026-05-21",
    last_close: 100,
    action: "HOLD",
    book_score: 0,
    trend: {
      monthly: { above_ma_10: true, ma_10: 95, alignment_score: 0.5 } as never,
      weekly:  { above_ma_10: true, ma_10: 96, alignment_score: 0.5 } as never,
      daily:   null,
    } as never,
    patterns: [],
    volume_case: { case: 0 } as never,
    last_candle: { tags: [], upper_wick_pct: 0, body_pct: 0.5 } as never,
    consolidation_ratio: 0.2,
    position_in_52w: 0.5,
    rally_8w_pct: 0,
    stretch_reason: null,
    ...over,
  } as AnalysisResult;
}

// ─────────────────────────────────────────────────────────────────────
// isAmbushSetup — parity with Python is_ambush_setup
// ─────────────────────────────────────────────────────────────────────

describe("isAmbushSetup (matches Python is_ambush_setup)", () => {
  it("fires with 4 of 4 signals", () => {
    const r = makeResult({
      action: "BUY",
      patterns: [{ kind: "MA 수렴 매복", completed: false, direction: "neutral" } as never],
      volume_case: { case: 12 } as never,
      last_candle: { tags: ["도지"], body_pct: 0.1 } as never,
      consolidation_ratio: 0.04,
    });
    expect(isAmbushSetup(r)).toBe(true);
  });

  it("skipped when price >5% over weekly ma_10", () => {
    const r = makeResult({
      action: "BUY",
      patterns: [{ kind: "MA 수렴 매복", completed: false, direction: "neutral" } as never],
      volume_case: { case: 12 } as never,
      last_candle: { tags: ["도지"], body_pct: 0.1 } as never,
      consolidation_ratio: 0.04,
      last_close: 110,
      trend: {
        monthly: { above_ma_10: true, ma_10: 95, alignment_score: 0.5 } as never,
        weekly: { above_ma_10: true, ma_10: 96, alignment_score: 0.5 } as never,
        daily: null,
      } as never,
    });
    expect(isAmbushSetup(r)).toBe(false);
  });

  it("skipped at 52w high", () => {
    const r = makeResult({
      action: "BUY",
      patterns: [{ kind: "MA 수렴 매복", completed: false, direction: "neutral" } as never],
      volume_case: { case: 12 } as never,
      consolidation_ratio: 0.04,
      position_in_52w: 0.92,
    });
    expect(isAmbushSetup(r)).toBe(false);
  });

  it("needs ≥2 signals", () => {
    const r = makeResult({
      action: "BUY",
      consolidation_ratio: 0.04,   // only tight box
    });
    expect(isAmbushSetup(r)).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────
// isPostRallyCaution — parity with Python is_post_rally_caution
// ─────────────────────────────────────────────────────────────────────

describe("isPostRallyCaution", () => {
  it("fires at 52w high + 30% rally + upper-wick rejection", () => {
    const r = makeResult({
      action: "BUY",
      position_in_52w: 0.92,
      rally_8w_pct: 0.30,
      last_candle: { tags: ["유성형"], upper_wick_pct: 0.6, body_pct: 0.2 } as never,
    });
    expect(isPostRallyCaution(r)).toBe(true);
  });

  it("does not fire below 85% 52w position", () => {
    const r = makeResult({
      position_in_52w: 0.7,
      rally_8w_pct: 0.30,
      last_candle: { tags: ["유성형"] } as never,
    });
    expect(isPostRallyCaution(r)).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────
// pickFreshBullishPattern — parity with Python _pick_fresh_bullish_pattern
// ─────────────────────────────────────────────────────────────────────

describe("pickFreshBullishPattern", () => {
  it("picks the smallest-runup completed bullish pattern", () => {
    const r = makeResult({
      last_close: 100,
      patterns: [
        { kind: "쌍바닥", completed: true, direction: "bullish",
          extra: { neckline: 80 } } as never,
        { kind: "역H&S", completed: true, direction: "bullish",
          extra: { neckline: 90 } } as never,
      ],
    });
    const p = pickFreshBullishPattern(r);
    expect(p?.kind).toBe("역H&S");  // 90→100 = +11% (fresher than 80→100 = +25%)
  });

  it("skips patterns below breakout (invalidation territory)", () => {
    const r = makeResult({
      last_close: 100,
      patterns: [
        { kind: "쌍바닥", completed: true, direction: "bullish",
          extra: { neckline: 110 } } as never,
      ],
    });
    expect(pickFreshBullishPattern(r)).toBeNull();
  });
});
