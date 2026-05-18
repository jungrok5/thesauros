/**
 * Regression coverage for two real bugs we shipped:
 *
 *   1. Search "샌디스크" / "구글" returned empty — Korean brand names
 *      don't appear inside our canonical corporate names ("Sandisk
 *      Corporation", "Alphabet Inc."). The fix: fall back to Naver
 *      Finance integrated search when our DB returns zero.
 *
 *   2. Visiting /stocks/GOOGLE and clicking 관찰 returned 500.
 *      `GOOGLE` isn't a real ticker; our resolveTicker couldn't find
 *      it (Alphabet's name doesn't contain "GOOGLE"), so it fell
 *      through to a non-canonical URL. The watchlist POST then hit a
 *      FK violation on `tickers(ticker)`.
 *
 * The prior `authed-watchlist.spec.ts` only exercised `AAPL`, which
 * IS in tickers, so the FK path was never tested. These cases close
 * that gap.
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

async function signInAs(page: import("@playwright/test").Page, email: string) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email },
  });
  expect(r.ok()).toBe(true);
  const body = await r.json();
  await page.context().addCookies([{
    name: body.cookieName,
    value: body.value,
    domain: "localhost",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
    expires: Math.floor(Date.now() / 1000) + 60 * 60,
  }]);
}

test.describe("Search Korean / brand-name fallback", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run authed E2E");

  test("Korean brand 샌디스크 finds SNDK via Naver fallback", async ({ page }) => {
    await signInAs(page, "search-test@e2e.test");
    const r = await page.request.get("/api/search?q=" + encodeURIComponent("샌디스크"));
    expect(r.ok(), `search failed: ${r.status()}`).toBe(true);
    const body = await r.json();
    const tickers = (body.items ?? []).map((x: { ticker: string }) => x.ticker);
    expect(tickers, "search returned zero results — Naver fallback failing")
      .toContain("SNDK");
  });

  test("Korean brand 애플 finds AAPL via Naver fallback", async ({ page }) => {
    await signInAs(page, "search-test@e2e.test");
    const r = await page.request.get("/api/search?q=" + encodeURIComponent("애플"));
    expect(r.ok()).toBe(true);
    const body = await r.json();
    const tickers = (body.items ?? []).map((x: { ticker: string }) => x.ticker);
    expect(tickers).toContain("AAPL");
  });
});

test.describe("Watchlist FK robustness", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run authed E2E");

  test("POST watchlist with a ticker that's missing from tickers master no longer 500s", async ({ page }) => {
    // Use a deliberately-unseeded marker so the test is reproducible
    // regardless of what's in `tickers` today. If this 500s, the FK
    // guard (`ensureTickerInMaster`) regressed.
    await signInAs(page, `fk-test-${Date.now()}@e2e.test`);
    const r = await page.request.post("/api/watchlist", {
      data: { ticker: "GOOGL", category: "observing" },
    });
    // Either ensureTickerInMaster inserted it (200) or it was already
    // there. The point: NOT 500.
    expect(r.status(), `watchlist POST should not 500: got ${r.status()}, body=${await r.text()}`)
      .toBeLessThan(500);
    expect(r.ok(), "watchlist POST should succeed for canonical US ticker").toBe(true);
  });

  test("POST watchlist with a brand-name string sane-fails instead of 500", async ({ page }) => {
    // 'GOOGLE' is not a canonical ticker. Even if Naver resolves it
    // upstream (via /api/search), POSTing it raw to /api/watchlist
    // must reject cleanly — not throw FK 500.
    await signInAs(page, `fk-test-2-${Date.now()}@e2e.test`);
    const r = await page.request.post("/api/watchlist", {
      data: { ticker: "GOOGLE", category: "observing" },
    });
    expect(r.status(), `watchlist POST should not 500: got ${r.status()}`)
      .toBeLessThan(500);
  });
});

test.describe("Stock detail Korean-name redirect", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run authed E2E");

  test("/stocks/샌디스크 resolves to SNDK and renders", async ({ page }) => {
    await signInAs(page, "stock-resolve@e2e.test");
    await page.goto("/stocks/" + encodeURIComponent("샌디스크"));
    // Resolver should redirect to canonical /stocks/SNDK; the header
    // shows the ticker prominently.
    await expect(page).toHaveURL(/\/stocks\/SNDK/, { timeout: 15_000 });
  });
});
