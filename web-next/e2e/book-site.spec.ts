import { test, expect } from "@playwright/test";

/**
 * E2E for the search-only site:
 *  - Auth-required pages (/watchlist, /stocks) redirect to /login when signed out
 *  - /api/watchlist returns 401 when signed out
 *
 * Removed pages: /recommendations, /closing-trade, /themes — those features
 * caused recurring false-positive false-positive bugs (LG우 type) due to
 * universe-wide auto-classification. The site now focuses on user-driven
 * search + on-demand analysis per ticker.
 */
test.describe("Search-only site — public routes redirect", () => {
  test("watchlist redirects to /login", async ({ page }) => {
    await page.goto("/watchlist");
    await expect(page).toHaveURL(/\/login(\?|$)/);
  });

  test("stocks redirects to /login", async ({ page }) => {
    await page.goto("/stocks");
    await expect(page).toHaveURL(/\/login(\?|$)/);
  });

  test("removed /recommendations renders 404 (not /login redirect)", async ({ page }) => {
    const r = await page.goto("/recommendations");
    // Next.js serves 404 for an unrouted path. Either status 404 or content
    // contains "404" / "not found" is acceptable — we just need to confirm
    // the page is gone, NOT that auth gate intercepts (which would mean
    // the route still exists).
    expect(r?.status() ?? 404).toBeGreaterThanOrEqual(404);
  });

  test("removed /closing-trade renders 404", async ({ page }) => {
    const r = await page.goto("/closing-trade");
    expect(r?.status() ?? 404).toBeGreaterThanOrEqual(404);
  });

  test("removed /themes renders 404", async ({ page }) => {
    const r = await page.goto("/themes");
    expect(r?.status() ?? 404).toBeGreaterThanOrEqual(404);
  });
});

test.describe("Chart proxy auth", () => {
  test("/api/chart without session → 401", async ({ request }) => {
    const r = await request.get("/api/chart?ticker=AAPL");
    expect(r.status()).toBe(401);
  });

  test("/api/chart with invalid ticker → 400 after auth would pass", async ({ request }) => {
    // Without session this still returns 401 first.
    const r = await request.get("/api/chart?ticker=$$$");
    expect([400, 401]).toContain(r.status());
  });
});

test.describe("Watchlist API auth gating", () => {
  test("GET /api/watchlist without session → 401", async ({ request }) => {
    const r = await request.get("/api/watchlist");
    expect(r.status()).toBe(401);
    const body = await r.json();
    expect(body.error).toBe("unauthorized");
  });

  test("POST /api/watchlist without session → 401", async ({ request }) => {
    const r = await request.post("/api/watchlist", {
      data: { ticker: "AAPL", category: "observing" },
    });
    expect(r.status()).toBe(401);
  });

  test("DELETE /api/watchlist without session → 401", async ({ request }) => {
    const r = await request.delete("/api/watchlist?ticker=AAPL");
    expect(r.status()).toBe(401);
  });
});
