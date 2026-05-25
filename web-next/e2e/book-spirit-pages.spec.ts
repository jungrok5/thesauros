/**
 * Page-level smoke + behavior tests for the book-spirit reorganization
 * (commits e3a7292..c542539).
 *
 * Each test asserts a single user-visible invariant on a real rendered
 * page — these are the kinds of regressions that static unit tests
 * don't catch (server/client boundary issues, layout drift, hidden
 * conditional rendering).
 *
 * Run:
 *   E2E_TEST_TOKEN=playwright-dev-only \
 *   E2E_BASE_URL=http://localhost:3000 \
 *   npx playwright test e2e/book-spirit-pages.spec.ts
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
// Public repo guard — admin email pulled from env, never hardcoded.
// Defaults to a generic `@e2e.test` address so a fork running these
// E2E tests doesn't accidentally hit the original maintainer's account.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@e2e.test";

async function signInAs(
  page: import("@playwright/test").Page,
  email: string,
  role: "admin" | "user" = "user",
) {
  const r = await page.request.post(`${BASE}/api/e2e-test/issue-session`, {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email, role },
  });
  expect(r.ok(), `issue-session: ${r.status()}`).toBe(true);
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

// ─────────────────────────────────────────────────────────────────────
// /welcome — the new rule book
// ─────────────────────────────────────────────────────────────────────

test.describe("/welcome — book-spirit rule documentation", () => {
  test("renders the data-refresh schedule table with all four cadences", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/welcome`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    // The new "데이터 갱신 일정" section must reach the user.
    await expect(body).toContainText("데이터 갱신 일정");
    // Four explicit time anchors — drift on any of these would mean a
    // user reading the doc gets a wrong mental model of when which data
    // is fresh.
    await expect(body).toContainText("매일 17 KST");
    await expect(body).toContainText("금요일 17 KST");
    await expect(body).toContainText("토요일 11 KST");
    await expect(body).toContainText("일요일 10 KST");
  });

  test("explains the 5 book-spirit core rules", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/welcome`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    await expect(body).toContainText("책 정신 핵심 규칙");
    // Each rule has a load-bearing phrase the user navigates by.
    await expect(body).toContainText("매매는 안 할수록 좋다");
    await expect(body).toContainText("주봉 종가가 결정 단위");
    await expect(body).toContainText("240MA");
    await expect(body).toContainText("거래량은 선행성");
    await expect(body).toContainText("4등분선");
  });

  test("explains the 4 alert modes including 와병투자", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/welcome`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    await expect(body).toContainText("결정 알림");
    await expect(body).toContainText("이벤트 알림");
    await expect(body).toContainText("가격 알림");
    await expect(body).toContainText("와병투자 모드");
  });

  test("FAQ includes the US-removed explanation", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/welcome`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText("미국 주식");
  });
});

// ─────────────────────────────────────────────────────────────────────
// /settings/alerts — bedrest mode + categorized toggles
// ─────────────────────────────────────────────────────────────────────

test.describe("/settings/alerts — bedrest mode + categories", () => {
  test("shows the 와병투자 toggle prominently at the top", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/settings/alerts`, { waitUntil: "domcontentloaded" });
    // The bedrest toggle has a dedicated data-testid for stable picking.
    await expect(page.locator("[data-testid='pref-bedrest_mode']")).toBeVisible();
    // 책-quote 가 와병투자 카드 안에 등장 — UI 가 책 정신 visualize.
    await expect(page.locator("body")).toContainText(/와병투자|한달 내내 누워있다|1회만 확인/);
  });

  test("groups toggles into the 4 categories the welcome page describes", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/settings/alerts`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    await expect(body).toContainText("결정 알림");
    await expect(body).toContainText("이벤트 알림");
    await expect(body).toContainText("가격 알림");
  });
});

// ─────────────────────────────────────────────────────────────────────
// NextDecisionChip — visible on the decision surfaces
// ─────────────────────────────────────────────────────────────────────

test.describe("NextDecisionChip — decision-surface visibility", () => {
  test("/screener shows the next-decision countdown", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText("다음 매매 결정");
    await expect(page.locator("body")).toContainText("15:30 KST");
  });

  test("/stocks/[ticker] shows the compact next-decision chip", async ({ page }) => {
    await signInAs(page, ADMIN_EMAIL);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    // Wait for the lazy analyze + auth + ticker resolution to settle.
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    await expect(page.locator("body")).toContainText("다음 결정");
  });
});

// chart-vision admin beta + /chart-vision page tests removed 2026-05-25 —
// the surface itself is gone (replaced first by us-analysis 2026-05-24,
// then dropped entirely on the site-direction reset). Sidebar gating
// invariants for admin-only items live in dedicated test files when
// new beta surfaces are introduced.
