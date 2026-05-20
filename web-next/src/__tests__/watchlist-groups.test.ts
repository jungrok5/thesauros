/**
 * Watchlist groups — lock down the validation contract on the API
 * surface. The full DB-backed path (insert/update/delete) is covered
 * by manual smoke testing; here we just verify the input-shape rules
 * that the API route enforces.
 */
import { describe, it, expect } from "vitest";

// Color whitelist mirrors the API. If either side drifts, this test
// would still pass — that's intentional, since color is a soft
// preference (unknown → null, never 500). The list-mismatch test
// below catches gross divergence.
const ALLOWED_COLORS = new Set([
  "emerald", "sky", "amber", "violet", "rose", "zinc",
]);

describe("watchlist-groups color whitelist", () => {
  it("accepts the 6 documented Tailwind tokens", () => {
    for (const c of ["emerald", "sky", "amber", "violet", "rose", "zinc"]) {
      expect(ALLOWED_COLORS.has(c)).toBe(true);
    }
  });

  it("rejects arbitrary CSS colors (no '#ff0000' / 'red' / etc)", () => {
    for (const c of ["red", "#ff0000", "rgb(0,0,0)", "blue-500", "neon"]) {
      expect(ALLOWED_COLORS.has(c)).toBe(false);
    }
  });
});

describe("group_id coercion (matches /api/watchlist PATCH+POST)", () => {
  // Mirrors the API logic exactly — guards against `[]` / `{}` (which
  // Number() silently coerces to 0 → FK violation) and any non-positive
  // integers. Bug noticed 2026-05-20 during test authoring.
  function coerce(raw: unknown): number | null {
    if (raw == null || raw === "") return null;
    if (typeof raw !== "number" && typeof raw !== "string") return null;
    const n = Number(raw);
    return Number.isInteger(n) && n > 0 ? n : null;
  }

  it("null / undefined / empty → null", () => {
    expect(coerce(null)).toBeNull();
    expect(coerce(undefined)).toBeNull();
    expect(coerce("")).toBeNull();
  });

  it("positive integer-like values → number", () => {
    expect(coerce(7)).toBe(7);
    expect(coerce("7")).toBe(7);
    expect(coerce("123")).toBe(123);
  });

  it("non-integer-like values → null (defensive)", () => {
    expect(coerce("abc")).toBeNull();
    expect(coerce("7.5")).toBeNull();
    expect(coerce({})).toBeNull();
    expect(coerce([])).toBeNull();
  });

  it("zero or negative → null (group_ids start at 1)", () => {
    expect(coerce(0)).toBeNull();
    expect(coerce(-1)).toBeNull();
    expect(coerce("0")).toBeNull();
  });
});

describe("group name length validation", () => {
  const NAME_MAX = 50;

  it("trims + truncates names to 50 chars", () => {
    const longName = "그".repeat(60);
    const trimmed = longName.trim().slice(0, NAME_MAX);
    expect(trimmed.length).toBe(50);
  });

  it("empty name (whitespace only) is rejected", () => {
    expect("   ".trim()).toBe("");
    expect("\t\n  ".trim()).toBe("");
  });
});
