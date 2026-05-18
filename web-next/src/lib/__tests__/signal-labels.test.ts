/**
 * Pin the Korean label + direction mapping so the page never regresses
 * to dumping `pattern_double_bottom` raw into the action column.
 *
 * Why this matters: a returning user clicked into recommendations and
 * couldn't tell whether each row was a buy or sell because the raw
 * snake_case signal_type was rendered. Direction inference is the
 * single most important UX detail of the page — any new signal added
 * MUST map here, and any rename MUST keep direction stable.
 */
import { describe, it, expect } from "vitest";
import {
  labelFor,
  isBullishPattern,
  isBearishPattern,
  BULLISH_PATTERN_KEYS,
  BEARISH_PATTERN_KEYS,
  directionStyle,
} from "@/lib/signal-labels";

describe("signal-labels", () => {
  it("bullish patterns are unambiguous buys", () => {
    for (const k of [
      "pattern_double_bottom",
      "pattern_triple_bottom",
      "pattern_inverse_head_and_shoulders",
      "pattern_forking",
      "pattern_cup_with_handle",
    ]) {
      expect(labelFor(k).direction).toBe("bullish");
      expect(isBullishPattern(k)).toBe(true);
      expect(isBearishPattern(k)).toBe(false);
    }
  });

  it("bearish patterns are unambiguous sells", () => {
    for (const k of [
      "pattern_double_top",
      "pattern_triple_top",
      "pattern_head_and_shoulders",
    ]) {
      expect(labelFor(k).direction).toBe("bearish");
      expect(isBearishPattern(k)).toBe(true);
      expect(isBullishPattern(k)).toBe(false);
    }
  });

  it("BULLISH_PATTERN_KEYS and BEARISH_PATTERN_KEYS are disjoint", () => {
    const bulls = new Set(BULLISH_PATTERN_KEYS);
    for (const b of BEARISH_PATTERN_KEYS) {
      expect(bulls.has(b)).toBe(false);
    }
  });

  it("never returns a raw snake_case label for known signals", () => {
    for (const k of [
      "pattern_double_bottom",
      "pattern_triple_top",
      "action_strong_buy",
      "action_sell_short",
      "volume_case_9",
    ]) {
      const { label } = labelFor(k);
      // Korean labels never contain '_'; raw snake_case always does.
      expect(label).not.toContain("_");
      expect(label.length).toBeGreaterThan(0);
    }
  });

  it("unknown signal type falls back to the raw key (so we can spot it)", () => {
    const out = labelFor("totally_unknown_signal");
    expect(out.label).toBe("totally_unknown_signal");
    expect(out.direction).toBe("neutral");
  });

  it("directionStyle returns distinct tones for bullish/bearish/neutral", () => {
    const bull = directionStyle("bullish");
    const bear = directionStyle("bearish");
    const neutral = directionStyle("neutral");
    expect(bull.text).not.toBe(bear.text);
    expect(bull.text).not.toBe(neutral.text);
    expect(bear.text).not.toBe(neutral.text);
  });
});
