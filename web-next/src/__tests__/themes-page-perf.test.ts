/**
 * Static guard for /themes performance regressions.
 *
 * Background — 2026-05-22: users reported `/themes` was very slow and
 * showed "테마 데이터 없음" placeholder even though the DB had 265
 * themes and 6,442 members. Root cause: the page exported
 * `dynamic = "force-dynamic"`, which defeats the `revalidate = 3600`
 * ISR cache. Every page-load called `theme_metrics()` directly — a
 * window-sort on 645k bars rows that takes 9-10 s cold. Combined with
 * Vercel's default 10 s function timeout, the rpc often timed out and
 * `fetchThemes()` returned an empty array, triggering the "weekly
 * cron으로 동기화 됩니다" placeholder.
 *
 * This guard pins three invariants so the regression can't sneak back:
 *
 *   1. `force-dynamic` is NOT exported (kills ISR).
 *   2. `revalidate` IS exported (enables ISR).
 *   3. `maxDuration` is set above the Vercel default (so cold revalidation
 *      doesn't time out either).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const PAGE_PATH = path.resolve(
  __dirname, "..", "app", "(app)", "themes", "page.tsx",
);

describe("/themes page — performance config invariants", () => {
  const src = fs.readFileSync(PAGE_PATH, "utf8");

  it("does not export `dynamic = 'force-dynamic'` (would defeat ISR)", () => {
    const FORCE_DYNAMIC =
      /export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/;
    expect(src).not.toMatch(FORCE_DYNAMIC);
  });

  it("exports a `revalidate` interval (enables ISR caching)", () => {
    const HAS_REVALIDATE = /export\s+const\s+revalidate\s*=\s*\d+/;
    expect(src).toMatch(HAS_REVALIDATE);
  });

  it("sets `maxDuration` above Vercel's 10s hobby-tier default", () => {
    // theme_metrics() RPC takes 9-10s cold; without bumping the
    // function ceiling the very first user after revalidation times
    // out and sees an empty page.
    const MAX_DURATION = /export\s+const\s+maxDuration\s*=\s*(\d+)/;
    const m = src.match(MAX_DURATION);
    expect(m, "maxDuration export missing").not.toBeNull();
    if (m) {
      expect(Number(m[1])).toBeGreaterThanOrEqual(20);
    }
  });

  it("distinguishes RPC error from empty-data state in the UI", () => {
    // Same placeholder for both cases hides the actual failure signal
    // from users and operators. Verify the page branches on a
    // dedicated error variable.
    expect(src).toMatch(/fetchError/);
  });
});
