/**
 * /dashboard renders entirely from Supabase (no FastAPI). Verifies the
 * page loads without the old "FastAPI 백엔드에 연결할 수 없습니다" banner
 * and shows real macro indicators.
 */
import { test, expect, type Page } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

async function signIn(page: Page) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: {
      email: `dash-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.test`,
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

test.describe("Dashboard from Supabase", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");

  test("renders without FastAPI", async ({ page }) => {
    await signIn(page);
    await page.goto("/dashboard");

    await expect(
      page.getByRole("heading", { name: "거시 환경", exact: true }),
    ).toBeVisible();

    // The old FastAPI error banner must NOT appear
    await expect(
      page.getByText("FastAPI 백엔드에 연결할 수 없습니다"),
    ).toHaveCount(0);

    // At least one indicator card / regime section should render
    await expect(page.getByText("시장 레짐", { exact: true })).toBeVisible();
  });
});
