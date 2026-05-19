/**
 * Static-analysis guard against the post-approval redirect loop.
 *
 * Discovered 2026-05-19: when an admin approved a user, the user's
 * JWT cookie still carried the older "pending" status, so:
 *   - proxy.ts saw pending → redirected /dashboard → /pending
 *   - /pending server component read DB → saw approved → redirected → /dashboard
 *   - ERR_TOO_MANY_REDIRECTS in the browser
 *
 * Fix kept two invariants which this test pins:
 *   1. /pending must NOT call `redirect("/dashboard")` (or anywhere
 *      else) when DB says approved — it should render an explicit
 *      "approved, click to continue" banner so the only way out is
 *      a user gesture that produces a fresh request and re-evaluates
 *      the JWT.
 *   2. auth.ts JWT callback must implement a TTL refresh so the
 *      cookie token catches up with DB state without a re-login.
 *
 * If a future refactor reintroduces either pattern this test fails.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "..", "..");
const PENDING_PAGE = path.join(
  ROOT, "src", "app", "pending", "page.tsx",
);
const AUTH_FILE = path.join(ROOT, "src", "auth.ts");

describe("post-approval redirect loop guard", () => {
  it("/pending page does NOT redirect approved users", () => {
    // Strip comments first so the bug-description prose (which intentionally
    // contains `redirect("/dashboard")` as a counter-example) doesn't trip
    // the check. Line comments + block comments both.
    const raw = fs.readFileSync(PENDING_PAGE, "utf8");
    const src = raw
      .replace(/\/\*[\s\S]*?\*\//g, "")     // /* ... */
      .replace(/(^|\s)\/\/[^\n]*/g, "");   // // ...
    // The exact bad pattern that caused the loop.
    const bad = [
      /status\s*===\s*["']approved["']\s*\)\s*redirect\(/,
      /redirect\(\s*["']\/dashboard["']\s*\)/,
    ];
    for (const re of bad) {
      expect(src).not.toMatch(re);
    }
    // The banner must be present — it's what replaces the redirect.
    expect(raw).toMatch(/ApprovedBanner|status-approved/);
  });

  it("auth.ts JWT callback implements TTL-based refresh", () => {
    const src = fs.readFileSync(AUTH_FILE, "utf8");
    // The TTL constant + the stale check pattern. If a future refactor
    // drops both, this fails — fix the refactor or update this test
    // with the new safety mechanism.
    expect(src).toMatch(/TTL_MS|_fetchedAt/);
    // Should not only refresh on sign-in — that was the bug.
    expect(src).toMatch(/stale|shouldRefresh|TTL/i);
  });
});
