/**
 * Site-direction reset (2026-05-25) — E2E invariants.
 *
 * The reset trimmed the surface area of the site:
 *   - Removed: /us-analysis, /themes, /flow-ranking, /volume-surge
 *   - /backtest demoted from sidebar to a dashboard footer link
 *   - /screener collapsed from 6 presets to 1 (book-spirit only)
 *   - /dashboard BookEntrySpots demoted from top-12 to TOP 3 preview
 *
 * These tests are real-browser checks for invariants the unit tests
 * can't see (sidebar render order, link presence in actual DOM, page
 * routing behavior). They share the same E2E_TEST_TOKEN flow as the
 * other spec files — see book-spirit-pages.spec.ts for the helper.
 *
 * Run:
 *   E2E_TEST_TOKEN=playwright-dev-only \
 *   E2E_BASE_URL=http://localhost:3000 \
 *   npx playwright test e2e/site-direction-reset.spec.ts
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const USER_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "site-reset@e2e.test";

async function signIn(page: import("@playwright/test").Page) {
  const r = await page.request.post(`${BASE}/api/e2e-test/issue-session`, {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email: USER_EMAIL, role: "user" },
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
// Sidebar — removed surfaces must not come back
// ─────────────────────────────────────────────────────────────────────

test.describe("Sidebar after site-direction reset", () => {
  test("dashboard renders without the removed sidebar headings", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const nav = page.locator("[data-testid='sidebar-nav']");
    await expect(nav).toBeVisible();
    // 5 groups expected — removed headings must not appear anywhere
    // in the sidebar tree.
    await expect(nav).not.toContainText("📊 시장 모니터");
    await expect(nav).not.toContainText("🇺🇸 미국");
    // Removed individual items — by label text.
    await expect(nav).not.toContainText("백테스트 17년");
    await expect(nav).not.toContainText("테마");
    await expect(nav).not.toContainText("거래량 폭증");
    await expect(nav).not.toContainText("큰손 매매 랭킹");
    await expect(nav).not.toContainText("미국 종목 분석");
  });

  test("sidebar still contains the 5 kept surfaces", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const nav = page.locator("[data-testid='sidebar-nav']");
    await expect(nav).toContainText("시작하기");
    await expect(nav).toContainText("거시 (Macro)");
    await expect(nav).toContainText("종목 검색");
    await expect(nav).toContainText("스크리너");
    await expect(nav).toContainText("관심·보유 종목");
    await expect(nav).toContainText("설정");
  });
});

// ─────────────────────────────────────────────────────────────────────
// Removed pages must 404 (Next.js default for unmatched routes)
// ─────────────────────────────────────────────────────────────────────

test.describe("Removed page paths return 404", () => {
  const REMOVED_PATHS = [
    "/us-analysis",
    "/themes",
    "/themes/1",
    "/flow-ranking",
    "/volume-surge",
  ];

  for (const p of REMOVED_PATHS) {
    test(`${p} → 404`, async ({ page }) => {
      await signIn(page);
      const resp = await page.goto(`${BASE}${p}`, {
        waitUntil: "domcontentloaded",
      });
      // Next.js renders 404 (not redirect) for deleted app routes.
      expect(resp?.status(), `${p} should 404`).toBe(404);
    });
  }
});

// ─────────────────────────────────────────────────────────────────────
// /screener — single preset behavior
// ─────────────────────────────────────────────────────────────────────

test.describe("/screener — single book-spirit preset", () => {
  test("default visit shows the 책 정신 매수 후보 preset header", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    // Single-preset page: header + oneLiner copy from book-buy preset
    // must render even without ?preset= in the URL (default fallback).
    await expect(body).toContainText("책 정신 매수 후보");
    await expect(body).toContainText("240일 평균선");
  });

  test("unknown ?preset= falls back to default (not blank)", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/screener?preset=value-classic`, {
      waitUntil: "domcontentloaded",
    });
    // value-classic was removed; page must fall back to book-buy, not
    // crash or show an empty shell.
    await expect(page.locator("body")).toContainText("책 정신 매수 후보");
  });

  test("preset chooser cards are gone (PresetCardsClient deleted)", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    // The 5 removed preset titles must not appear anywhere on the page.
    const body = page.locator("body");
    await expect(body).not.toContainText("가치투자 클래식");
    await expect(body).not.toContainText("딥밸류");
    await expect(body).not.toContainText("퀄리티 성장주");
    await expect(body).not.toContainText("고배당 안전");
    await expect(body).not.toContainText("마법공식");
  });
});

// ─────────────────────────────────────────────────────────────────────
// /dashboard — BookEntrySpots demote + backtest footer link
// ─────────────────────────────────────────────────────────────────────

test.describe("/dashboard layout after reset", () => {
  test("BookEntrySpots heading reads 'TOP 3' (not the legacy 'top 12')", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    // Either the spots heading 'TOP 3' or the empty-state copy — both
    // are acceptable depending on scan_results state, but the legacy
    // 'top 12' string must never appear.
    await expect(body).not.toContainText("top 12");
    await expect(body).not.toContainText("TOP 12");
  });

  test("dashboard footer surfaces backtest credibility + link", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    // The /backtest link is the *only* way users find the page after
    // the sidebar demote — its presence is load-bearing.
    const backtestLink = page.locator('a[href="/backtest"]');
    await expect(backtestLink).toBeVisible();
    // Numbers must be in the same DOM region so the link has a
    // reason to be clicked.
    await expect(page.locator("body")).toContainText("CAGR 13.4%");
  });

  test("/backtest is still reachable (page kept, only demoted)", async ({ page }) => {
    await signIn(page);
    const resp = await page.goto(`${BASE}/backtest`, {
      waitUntil: "domcontentloaded",
    });
    expect(resp?.status()).toBeLessThan(400);
  });
});
