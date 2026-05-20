/**
 * Lock down: heavy server-data pages MUST have a loading.tsx so
 * Next.js can show instant feedback during navigation.
 *
 * Bug fixed 2026-05-20: 0 loading.tsx existed → users reported
 * "사이트가 느릿느릿한 느낌". Now any page that does substantial
 * server-side data fetching gets a skeleton that paints immediately
 * on click.
 *
 * If you add a new page that hits Supabase / external APIs in
 * server code, add a sibling loading.tsx so the navigation feels
 * instant.
 */
import { describe, it, expect } from "vitest";
import { existsSync } from "fs";
import { join } from "path";

const APP = join(__dirname, "..", "app", "(app)");

const PAGES_REQUIRING_LOADING = [
  // Base fallback — covers any page not listed below
  "",  // (app)/loading.tsx
  // Heavy data pages
  "stocks/[ticker]",
  "watchlist",
  "dashboard",
  "screener",
  "flow-ranking",
  "volume-surge",
];

describe("loading.tsx skeletons exist for heavy pages", () => {
  for (const subpath of PAGES_REQUIRING_LOADING) {
    const label = subpath || "(app) base";
    it(`${label} has loading.tsx`, () => {
      const p = join(APP, subpath, "loading.tsx");
      expect(existsSync(p), `missing: ${p}`).toBe(true);
    });
  }
});
