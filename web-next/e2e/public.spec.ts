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
    // Brand is in an eyebrow above the h1; the h1 itself is the
    // product tagline. Assert both so the test pins the visual layout.
    await expect(page.getByText("Thesauros", { exact: true })).toBeVisible();
    await expect(page.locator("h1")).toHaveText("추세추종 매매 도구");
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
