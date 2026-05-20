/**
 * Lock down the server/client module boundary for /watchlist —
 * specifically the regression that caused Vercel ERROR 1025776953
 * on 2026-05-20:
 *
 *   app/(app)/watchlist/page.tsx (server component) imported the
 *   plain util `groupColorClass` from group-manager-client.tsx
 *   (which has "use client"). Local dev tolerated this, but the
 *   Vercel build/runtime crashed because Next.js's React Server
 *   Components contract disallows server modules importing
 *   runtime (non-component) values from client modules.
 *
 *   Fix: moved `groupColorClass` + `COLOR_OPTIONS` to a sibling
 *   plain .ts file (group-colors.ts) so both server and client
 *   can import safely.
 *
 * This test reads the actual sources and asserts the structural
 * invariant — much faster than a Playwright build smoke test, and
 * catches the bug before it ships.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..", "app", "(app)", "watchlist");

function read(name: string): string {
  return readFileSync(join(ROOT, name), "utf-8");
}

function isClientModule(src: string): boolean {
  // Match the first non-comment, non-empty line
  for (const line of src.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    if (s.startsWith("//") || s.startsWith("/*") || s.startsWith("*")) continue;
    return s.startsWith('"use client"') || s.startsWith("'use client'");
  }
  return false;
}

describe("watchlist module boundaries", () => {
  it("group-colors.ts is a plain module (NOT 'use client')", () => {
    // The fix: groupColorClass lives in a non-client module so both
    // page.tsx (server) and group-manager-client.tsx (client) can
    // import it without crossing the RSC boundary.
    const src = read("group-colors.ts");
    expect(isClientModule(src)).toBe(false);
    // And it exports what we need:
    expect(src).toMatch(/export\s+function\s+groupColorClass/);
    expect(src).toMatch(/export\s+const\s+COLOR_OPTIONS/);
  });

  it("group-manager-client.tsx IS a 'use client' module", () => {
    const src = read("group-manager-client.tsx");
    expect(isClientModule(src)).toBe(true);
  });

  it("page.tsx imports groupColorClass from group-colors (NOT from -client.tsx)", () => {
    const src = read("page.tsx");
    // The exact regression: importing from group-manager-client would
    // re-introduce ERROR 1025776953.
    expect(src).not.toMatch(/groupColorClass.*from\s*["']\.\/group-manager-client/);
    // It MUST come from group-colors.
    expect(src).toMatch(/import\s*\{\s*groupColorClass\s*\}\s*from\s*["']\.\/group-colors["']/);
  });

  it("page.tsx is NOT a 'use client' module (must stay server-rendered)", () => {
    // The fix flow expects page.tsx to remain a server component so it
    // can run Supabase + auth() server-side. If someone accidentally
    // adds "use client" to page.tsx, it breaks the auth gate.
    const src = read("page.tsx");
    expect(isClientModule(src)).toBe(false);
  });
});
