/**
 * E2E for the mobile hamburger drawer.
 *
 * On phones (sidebar is hidden via `hidden md:flex`), the only way to reach
 * other pages is the hamburger drawer. This test verifies:
 *   - the toggle exists on small viewports
 *   - clicking opens the drawer with the nav inside
 *   - clicking a link navigates AND closes the drawer
 *   - clicking the backdrop closes the drawer without navigating
 *   - the drawer is not present at md+ (desktop sidebar takes over)
 */
import { test, expect, type Page } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

async function signInAsApproved(page: Page) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: {
      email: `mobile-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.test`,
      role: "user",
      access_status: "approved",
    },
  });
  expect(r.ok(), `issue-session failed: ${r.status()}`).toBe(true);
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

test.describe("Mobile nav drawer", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");
  test.use({ viewport: { width: 390, height: 844 } });   // iPhone 13/14 size

  test("hamburger opens drawer with nav, link click navigates + closes", async ({ page }) => {
    await signInAsApproved(page);
    await page.goto("/dashboard");

    const toggle = page.getByTestId("mobile-nav-toggle");
    await expect(toggle).toBeVisible();

    await toggle.click();
    const drawer = page.getByTestId("mobile-nav-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("관심 종목");

    // Click a nav link → navigates and drawer closes
    await drawer.getByRole("link", { name: /관심 종목/ }).click();
    await expect(page).toHaveURL(/\/watchlist$/);
    await expect(page.getByTestId("mobile-nav-drawer")).toHaveCount(0);
  });

  test("backdrop click closes drawer without navigating", async ({ page }) => {
    await signInAsApproved(page);
    await page.goto("/dashboard");

    await page.getByTestId("mobile-nav-toggle").click();
    await expect(page.getByTestId("mobile-nav-drawer")).toBeVisible();

    // Programmatic dispatch — avoids any z-index / viewport quirks where
    // Playwright's hit-test routes the click through to the drawer panel.
    await page.locator('[data-testid="mobile-nav-backdrop"]').dispatchEvent("click");

    await expect(page.getByTestId("mobile-nav-drawer")).toHaveCount(0);
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("at desktop width, hamburger is hidden", async ({ page }) => {
    test.skip();   // viewport scoped via test.use; we cover the negative case below
  });
});

test.describe("Desktop sidebar — no hamburger", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");
  test.use({ viewport: { width: 1280, height: 800 } });

  test("desktop hides hamburger and shows persistent sidebar nav", async ({ page }) => {
    await signInAsApproved(page);
    await page.goto("/dashboard");

    await expect(page.getByTestId("mobile-nav-toggle")).toBeHidden();
    await expect(page.getByTestId("sidebar-nav")).toBeVisible();
  });
});
