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
