import { test, expect } from "@playwright/test";

/**
 * Regression: a friend opening a shared `/stocks/017670.KS` link should
 * end up back on that page after sign-in — not bounced to /dashboard.
 *
 * Was broken before because:
 *  1. The signed-out redirect (proxy.ts) used a bare `new URL("/login", ...)`
 *     without preserving the requested path.
 *  2. The login page hard-coded `signIn("google", { redirectTo: "/dashboard" })`.
 *
 * Both fixes need to be tested, but we can only assert what's visible
 * pre-auth without OAuth: that the URL carries `callbackUrl=<original>`.
 */

test.describe("Shared-link callbackUrl preservation", () => {
  test("stocks/[ticker] → /login keeps callbackUrl in the URL", async ({ page }) => {
    await page.goto("/stocks/005930.KS");
    await page.waitForURL(/\/login\?/, { timeout: 5_000 });
    const url = new URL(page.url());
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("callbackUrl")).toBe("/stocks/005930.KS");
  });

  test("recommendations → /login keeps callbackUrl with querystring", async ({ page }) => {
    await page.goto("/recommendations?sort=fresh&signal=buy");
    await page.waitForURL(/\/login\?/, { timeout: 5_000 });
    const url = new URL(page.url());
    expect(url.pathname).toBe("/login");
    const cb = url.searchParams.get("callbackUrl");
    expect(cb).toBeTruthy();
    expect(cb).toMatch(/^\/recommendations/);
    // Querystring should survive intact.
    expect(cb).toContain("sort=fresh");
    expect(cb).toContain("signal=buy");
  });

  test("/dashboard → /login carries dashboard as callbackUrl", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForURL(/\/login(\?|$)/, { timeout: 5_000 });
    const url = new URL(page.url());
    const cb = url.searchParams.get("callbackUrl");
    expect(cb).toBe("/dashboard");
  });

  test("login page renders Google button even with callbackUrl set", async ({ page }) => {
    // Ensures the page doesn't crash on a weird callbackUrl value.
    await page.goto("/login?callbackUrl=%2Fstocks%2F017670.KS");
    await expect(page.getByRole("button", { name: /Google/ })).toBeVisible();
  });

  test("login page rejects open-redirect attempts (renders Google + falls back internally)", async ({ page }) => {
    // The attacker would pass an external URL; the sanitizer keeps the page
    // safe by mapping it to /dashboard. We can only assert the page still
    // loads — OAuth roundtrip can't be tested here — but the unit suite
    // (safe-redirect.test.ts) pins the sanitizer behavior.
    await page.goto("/login?callbackUrl=//evil.example.com");
    await expect(page.getByRole("button", { name: /Google/ })).toBeVisible();
  });
});
