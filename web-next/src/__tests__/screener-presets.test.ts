/**
 * Screener presets — registry + slug lookup.
 *
 * 2026-05-25 site-direction reset: down to a single book-spirit preset.
 * Tests focus on (a) registry sanity, (b) book-buy preset still uses
 * actionIn (multi-action) not single action — caught a prior regression
 * where STRONG_BUY 종목이 자동 제외되던 사고.
 *
 * If anyone re-adds a value-investing preset (마법공식 / 딥밸류 / etc.)
 * the assertion list at the bottom will fail — forcing a re-read of
 * feedback_site_direction.md before the reset gets walked back.
 */
import { describe, it, expect } from "vitest";
import { PRESETS, findPreset, DEFAULT_PRESET_SLUG } from "@/lib/screener-presets";

describe("PRESETS registry", () => {
  it("every preset has the required user-facing fields", () => {
    for (const p of PRESETS) {
      expect(p.slug, p.slug).toBeTruthy();
      expect(p.emoji, p.slug).toBeTruthy();
      expect(p.title, p.slug).toBeTruthy();
      expect(p.oneLiner.length, p.slug).toBeGreaterThan(10);
      expect(p.action.length, p.slug).toBeGreaterThan(10);
    }
  });

  it("slugs are unique (no silent route collision)", () => {
    const slugs = PRESETS.map((p) => p.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("filter is a plain object (not undefined or null)", () => {
    for (const p of PRESETS) {
      expect(typeof p.filter).toBe("object");
      expect(p.filter).not.toBeNull();
    }
  });

  it("DEFAULT_PRESET_SLUG resolves to an entry in PRESETS", () => {
    expect(findPreset(DEFAULT_PRESET_SLUG)).not.toBeNull();
  });
});

describe("book-buy 강매수 포함 (2026-05-20 fix)", () => {
  // The bug: book-buy preset 의 filter 가 action="BUY" 단일값이라
  // STRONG_BUY 종목이 자동 제외됨. 사용자가 "강매수 안 보임" 보고.
  // Fix: actionIn=["STRONG_BUY","BUY"] 으로 둘 다 통과.
  const preset = PRESETS.find((p) => p.slug === "book-buy")!;

  it("preset exists", () => {
    expect(preset).toBeDefined();
  });

  it("uses actionIn (multi-action)", () => {
    expect(preset.filter.actionIn).toBeDefined();
  });

  it("actionIn includes both STRONG_BUY and BUY", () => {
    expect(preset.filter.actionIn).toContain("STRONG_BUY");
    expect(preset.filter.actionIn).toContain("BUY");
  });

  it("bookScoreMin / roeMin still applied", () => {
    expect(preset.filter.bookScoreMin).toBe(0.7);
    expect(preset.filter.roeMin).toBe(0.05);
  });
});

describe("findPreset", () => {
  it("returns the preset object for a known slug", () => {
    const p = findPreset("book-buy");
    expect(p).not.toBeNull();
    expect(p?.slug).toBe("book-buy");
  });

  it("returns null for unknown slug", () => {
    expect(findPreset("does-not-exist")).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(findPreset(undefined)).toBeNull();
  });

  it("returned reference is identical to the entry in PRESETS", () => {
    const p = findPreset("book-buy");
    expect(p).toBe(PRESETS.find((x) => x.slug === "book-buy"));
  });
});

describe("removed presets stay removed (site-direction reset 2026-05-25)", () => {
  // Each removed preset was a value-investing philosophy that conflicts
  // with the book's trend-following stance. Adding any back without an
  // explicit decision means walking into the same trap again — read
  // feedback_site_direction.md before deleting these assertions.
  const REMOVED = [
    "value-classic",      // 그레이엄 + 버핏
    "value-deep",         // 저PER + 저PBR (딥밸류)
    "growth-quality",     // 퀄리티 성장주 (펀더 중심)
    "high-dividend-safe", // 고배당 안전
    "magic-formula",      // 그린블랫 마법공식
  ];

  for (const slug of REMOVED) {
    it(`'${slug}' is not in PRESETS`, () => {
      expect(PRESETS.find((p) => p.slug === slug)).toBeUndefined();
    });
  }
});
