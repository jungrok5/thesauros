/**
 * Screener presets — registry shape + slug lookup.
 *
 * Catches:
 *   - Duplicate slugs (route conflict — second one wins silently).
 *   - Empty title / oneLiner / action (UI shows blank cards).
 *   - Filter object referencing a field that no longer exists on the
 *     ScreenerFilter type (type-checked elsewhere but smoke-tested here).
 *   - findPreset returning a different object than what's in PRESETS
 *     (would break dynamic route → preset binding).
 */
import { describe, it, expect } from "vitest";
import { PRESETS, findPreset, type ScreenerPreset } from "@/lib/screener-presets";

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
});

describe("growth-quality 거품 제외 (2026-05-20 fix)", () => {
  // The bug: original filter had no PBR/PER cap, so 에이피알 PBR 33배 +
  // SK하이닉스 PBR 10배 통과. "퀄리티 성장주" 인데 거품주가 노출되는
  // 모순. Cap PBR ≤ 5 + PER ≤ 40 so growth + sane pricing 동시 합격.
  const preset = PRESETS.find((p) => p.slug === "growth-quality")!;

  it("has pbrMax and perMax caps", () => {
    expect(preset.filter.pbrMax).toBe(5);
    expect(preset.filter.perMax).toBe(40);
  });

  it("growth + ROE thresholds remain unchanged", () => {
    expect(preset.filter.revenueGrowthMin).toBe(0.10);
    expect(preset.filter.roeMin).toBe(0.15);
    expect(preset.filter.debtRatioMax).toBe(1.0);
  });

  it("oneLiner mentions the cap so users know what's excluded", () => {
    // If someone removes the cap, the oneLiner becomes a lie — fail
    // the test so the rationale is preserved in the UI copy.
    expect(preset.oneLiner).toMatch(/거품|PBR|PER/);
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
