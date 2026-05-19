/**
 * Open-redirect guard for the login page's callbackUrl. Without this
 * sanitizer an attacker could craft `/login?callbackUrl=//evil.com/x`
 * and the post-Google-OAuth redirect would land the victim on the
 * attacker's site. We MUST keep these invariants pinned.
 */
import { describe, it, expect } from "vitest";
import { safeCallback } from "@/lib/safe-redirect";

describe("safeCallback", () => {
  it("returns /dashboard for null/empty/undefined", () => {
    expect(safeCallback(undefined)).toBe("/dashboard");
    expect(safeCallback("")).toBe("/dashboard");
  });

  it("returns /dashboard for absolute URLs (open-redirect attempt)", () => {
    expect(safeCallback("https://evil.com")).toBe("/dashboard");
    expect(safeCallback("http://evil.com/path")).toBe("/dashboard");
    expect(safeCallback("ftp://x")).toBe("/dashboard");
  });

  it("returns /dashboard for protocol-relative URLs", () => {
    expect(safeCallback("//evil.com")).toBe("/dashboard");
    expect(safeCallback("//evil.com/x?y=z")).toBe("/dashboard");
  });

  it("returns /dashboard for backslash-escape tricks", () => {
    // Some browsers normalise "/\\foo" to "//foo" → external.
    expect(safeCallback("/\\evil.com")).toBe("/dashboard");
  });

  it("returns /dashboard for paths that don't start with /", () => {
    expect(safeCallback("dashboard")).toBe("/dashboard");
    expect(safeCallback("evil.com/x")).toBe("/dashboard");
  });

  it("allows ordinary same-site paths through unchanged", () => {
    expect(safeCallback("/stocks/017670.KS")).toBe("/stocks/017670.KS");
    expect(safeCallback("/watchlist?sort=fresh")).toBe(
      "/watchlist?sort=fresh",
    );
    expect(safeCallback("/dashboard")).toBe("/dashboard");
  });

  it("respects custom fallback when provided", () => {
    expect(safeCallback(undefined, "/")).toBe("/");
    expect(safeCallback("//evil", "/")).toBe("/");
  });
});
