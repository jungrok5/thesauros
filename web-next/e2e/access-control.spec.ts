/**
 * E2E for the new access-control workflow:
 *   - pending user is redirected to /pending and can submit a request
 *   - admin sees the request on /admin/access and can approve
 *   - approved user can hit /dashboard and /api/watchlist
 *   - non-admin cannot reach /admin/access or /api/admin/*
 *   - hydration on /pending and /admin/access
 *
 * Uses the test-only `/api/e2e-test/issue-session` endpoint which now
 * accepts `role` and `access_status` to mint cookies for any state.
 */
import { test, expect, type Page } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

type Role = "admin" | "user";
type Status = "pending" | "approved" | "rejected";

async function signInAs(
  page: Page,
  email: string,
  role: Role = "user",
  access_status: Status = "approved",
) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email, role, access_status },
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
  return body.userId as string;
}

async function clearSession(page: Page) {
  await page.context().clearCookies();
}

function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.test`;
}

const HYDRATION_NEEDLES = [
  "Hydration failed",
  "did not match",
  "Encountered a script tag while rendering React component",
];

function hookErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

test.describe("Access control", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");

  test("pending user is redirected to /pending and can submit a request", async ({ page }) => {
    const email = uniqueEmail("pending");
    await signInAs(page, email, "user", "pending");

    // Hitting /dashboard bounces to /pending
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/pending$/);

    // status banner is the 'new' one (no request yet)
    await expect(page.getByTestId("status-new")).toBeVisible();

    // submit a request
    await page.getByTestId("pending-reason").fill("e2e test access request");
    await page.getByTestId("pending-submit").click();

    // after refresh, the banner flips to 'pending'
    await expect(page.getByTestId("status-pending")).toBeVisible();
  });

  test("approved user reaches dashboard + watchlist API", async ({ page }) => {
    const email = uniqueEmail("approved");
    await signInAs(page, email, "user", "approved");

    await page.goto("/dashboard");
    await expect(page).not.toHaveURL(/\/pending/);

    const watch = await page.request.get("/api/watchlist");
    expect(watch.status()).toBe(200);
  });

  test("non-admin cannot reach /admin/access (page redirect)", async ({ page }) => {
    const email = uniqueEmail("plain");
    await signInAs(page, email, "user", "approved");

    await page.goto("/admin/access");
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("non-admin gets 403 on /api/admin/access-requests", async ({ page }) => {
    const email = uniqueEmail("plain2");
    await signInAs(page, email, "user", "approved");

    const r = await page.request.get("/api/admin/access-requests");
    expect(r.status()).toBe(403);
  });

  test("admin can list and approve a pending user", async ({ page }) => {
    // 1) create a pending user via the issue-session endpoint
    const pendingEmail = uniqueEmail("toapprove");
    const adminPage1 = await page.context().newPage();
    const pendingUserId = await signInAs(adminPage1, pendingEmail, "user", "pending");
    await adminPage1.close();

    // 2) become admin
    await clearSession(page);
    const adminEmail = uniqueEmail("admin");
    await signInAs(page, adminEmail, "admin", "approved");

    // sidebar shows admin link
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toContainText("관리자");

    // 3) approve the pending user via API (UI uses confirm() which is hard
    //    to drive across page.goto refreshes; the API is what we care about)
    const approveResp = await page.request.post("/api/admin/access-requests", {
      data: { user_id: pendingUserId, decision: "approved" },
    });
    expect(approveResp.status()).toBe(200);

    // 4) verify the listing shows them in 'approved'
    const list = await page.request.get(
      "/api/admin/access-requests?status=approved",
    );
    const body = await list.json();
    const emails: string[] = (body.items ?? []).map((u: { email: string }) => u.email);
    expect(emails).toContain(pendingEmail);
  });

  test("hydration: /pending and /admin/access render without errors", async ({ page }) => {
    const errors = hookErrors(page);
    await signInAs(page, uniqueEmail("hyd1"), "user", "pending");
    await page.goto("/pending", { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    await clearSession(page);
    await signInAs(page, uniqueEmail("hyd2"), "admin", "approved");
    await page.goto("/admin/access", { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    const hydration = errors.filter((e) =>
      HYDRATION_NEEDLES.some((n) => e.toLowerCase().includes(n.toLowerCase())),
    );
    expect(hydration, hydration.join("\n")).toEqual([]);
  });
});
