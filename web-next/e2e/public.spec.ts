import { test, expect } from "@playwright/test";

/**
 * Public (signed-out) flow:
 *  - Visiting /dashboard redirects to /login
 *  - /login renders the Thesauros branding + Google button
 */
test.describe("Public routes", () => {
  test("dashboard redirects to /login when signed out", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login(\?|$)/);
    await expect(page.locator("h1")).toHaveText("Thesauros");
  });

  test("login page shows Google sign-in", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("button", { name: /Google/ })).toBeVisible();
  });

  test("root redirects to dashboard (then login)", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/login(\?|$)/, { timeout: 5_000 });
  });
});
