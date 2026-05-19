/**
 * Static-analysis guard: pages under `(app)/` MUST NOT export
 * `dynamic = "force-static"`.
 *
 * Why: the `(app)/layout.tsx` calls `auth()` and `redirect("/login")` when
 * there's no session. With `force-static`, Next.js prerenders the page at
 * build time when `auth()` returns null → the `redirect("/login")` gets
 * baked into the static HTML. Hard refresh in the browser then serves
 * that cached redirect, kicking the user back to `/login` even though
 * they're logged in.
 *
 * (Discovered 2026-05-19 — /guide and /glossary were both affected.)
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.isFile() && e.name === "page.tsx") out.push(p);
  }
  return out;
}

describe("auth-protected pages: no force-static", () => {
  const appDir = path.resolve(__dirname, "..", "app", "(app)");

  it("(app) directory exists", () => {
    expect(fs.existsSync(appDir)).toBe(true);
  });

  const pages = fs.existsSync(appDir) ? walk(appDir) : [];

  // Quoted variants of the literal `force-static`. Allow trailing
  // whitespace/semicolon but require the property assignment exactly so
  // that documentation/comments mentioning the string don't trigger.
  const FORCE_STATIC = /export\s+const\s+dynamic\s*=\s*["']force-static["']/;

  for (const p of pages) {
    const rel = path.relative(appDir, p);
    it(`${rel} does not force-static (conflicts with layout auth)`, () => {
      const src = fs.readFileSync(p, "utf8");
      expect(src).not.toMatch(FORCE_STATIC);
    });
  }
});
