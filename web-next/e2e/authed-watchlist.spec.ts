/**
 * Authed Playwright tests — exercises Watchlist CRUD through the API.
 *
 * Approach (NextAuth + Playwright):
 *   Auth.js stores its session as a JWT inside an HTTP-only cookie
 *   `authjs.session-token`. We use the same `encode` helper Auth.js uses
 *   (HKDF-derived A256CBC-HS512 from AUTH_SECRET) to mint a valid JWT
 *   on the test side, then set the cookie via `page.context().addCookies()`.
 *
 *   To avoid depending on the encode internals, this test fixture mints the
 *   token by *calling* an internal route the dev server exposes — see
 *   `src/app/api/__test__/issue-session/route.ts`. The route is enabled only
 *   when E2E_TEST_TOKEN matches a header value (guard against accidents).
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@e2e.test";

async function signInAs(page: import("@playwright/test").Page, email: string) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email },
  });
  expect(r.ok()).toBe(true);
  const body = await r.json();
  // Set the cookie returned by the helper on the browser context.
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

test.describe("Watchlist authed CRUD", () => {
  test("POST adds, GET lists, DELETE removes", async ({ page, request }) => {
    test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run authed E2E");
    await signInAs(page, ADMIN_EMAIL);

    const ticker = "AAPL";

    // POST add
    const add = await page.request.post("/api/watchlist", {
      data: { ticker, category: "observing" },
    });
    expect(add.ok()).toBe(true);

    // GET list contains it
    const list = await page.request.get("/api/watchlist");
    expect(list.ok()).toBe(true);
    const listBody = await list.json();
    expect((listBody.items ?? []).map((x: { ticker: string }) => x.ticker)).toContain(ticker);

    // DELETE
    const del = await page.request.delete(`/api/watchlist?ticker=${ticker}`);
    expect(del.ok()).toBe(true);

    // GET list no longer contains it
    const list2 = await page.request.get("/api/watchlist");
    const list2Body = await list2.json();
    expect((list2Body.items ?? []).map((x: { ticker: string }) => x.ticker)).not.toContain(ticker);
  });

  test("watchlist page renders for signed-in user", async ({ page }) => {
    test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run authed E2E");
    await signInAs(page, ADMIN_EMAIL);
    await page.goto("/watchlist");
    await expect(page.getByRole("heading", { name: /관심 종목/ })).toBeVisible();
  });
});
