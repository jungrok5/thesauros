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

// ─────────────────────────────────────────────────────────────────────
// Dashboard ↔ /screener data-source alignment (2026-05-26 fix)
// ─────────────────────────────────────────────────────────────────────

test.describe("Dashboard ↔ /screener ticker alignment", () => {
  // The reason this test exists: the prior BookEntrySpots used the raw
  // scan_results table while /screener used the screener_results RPC.
  // Real-data review showed 0% overlap on the top 3 — one of the
  // dashboard's TOP 3 wasn't in the screener at all. After the
  // unification (BookEntrySpots → screener_results RPC), the dashboard
  // preview should *be* the first 3 rows of the screener list.
  test("dashboard TOP 3 tickers match the first 3 of /screener", async ({ page }) => {
    await signIn(page);

    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const dashHtml = await page.content();
    // Tickers inside the BookEntrySpots <a href="/stocks/...?from=dashboard">.
    const dashTickers = [
      ...dashHtml.matchAll(/\/stocks\/([A-Z0-9.]+)\?from=dashboard/g),
    ].map((m) => m[1]);
    // Dedup keeping order (mobile + desktop render the same link twice).
    const dashUnique: string[] = [];
    for (const t of dashTickers) {
      if (!dashUnique.includes(t)) dashUnique.push(t);
    }

    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    const scrnHtml = await page.content();
    const scrnTickers = [
      ...scrnHtml.matchAll(/\/stocks\/([A-Z0-9.]+)\?from=screener/g),
    ].map((m) => m[1]);
    const scrnUnique: string[] = [];
    for (const t of scrnTickers) {
      if (!scrnUnique.includes(t)) scrnUnique.push(t);
    }

    // If either surface has no data (cron hasn't run / DB empty),
    // skip — the alignment is undefined, not violated.
    if (dashUnique.length === 0 || scrnUnique.length === 0) {
      test.skip(true, "no candidate data on either surface");
      return;
    }

    // The unification guarantee: dashboard preview = first N of screener.
    const dashTop = dashUnique.slice(0, 3);
    const scrnTop = scrnUnique.slice(0, 3);
    expect(dashTop, "dashboard TOP 3 must equal screener TOP 3").toEqual(scrnTop);
  });
});

// ─────────────────────────────────────────────────────────────────────
// /stocks/[ticker] cleanup — value-investing card gone
// ─────────────────────────────────────────────────────────────────────

test.describe("/stocks/[ticker] book-spirit consistency", () => {
  test("stock detail page no longer shows the '가치투자 통과' card", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    // The card had this exact label; it lived in FundamentalVerdicts grid.
    // Removed in the alignment cycle so the screener's book-spirit-only
    // stance isn't contradicted on the detail page.
    await expect(page.locator("body")).not.toContainText("가치투자 통과");

    // The other half of the strip ("재무 건전성") stays — that one is
    // pure 안전성/수익성 evaluation, not a value-investing frame.
    // Skipped if the financials_eval row is missing for this ticker
    // (empty component renders nothing).
  });

  // 2026-05-26 reviewer pass: 외부 의견 (애널/큰손/실적) 이 결론 뒤에
  // 풀로 펼쳐져 있어서 초보가 결론을 흔들렸음. default fold 로 demote.
  test("외부 의견 · 일정 is rendered inside a <details> (collapsed by default)", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    const html = await page.content();
    // Section may not render at all if all 3 source tables are empty —
    // skip in that case (the assertion is about HOW it renders, not that
    // it always renders).
    if (!html.includes("외부 의견 · 일정")) {
      test.skip(true, "no consensus/holders/earnings data for 005930.KS");
      return;
    }
    // The heading must sit inside a <summary> tag (the <details> trigger),
    // not inside an <h2> as the prior layout had it.
    expect(html).toMatch(
      /<summary[^>]*>[\s\S]{0,300}외부 의견 · 일정[\s\S]{0,200}<\/summary>/,
    );
    // And the parent details must NOT carry `open` — default collapsed.
    const detailsOpenMatch = html.match(
      /<details\s+open[^>]*>[\s\S]{0,500}외부 의견 · 일정/,
    );
    expect(detailsOpenMatch, "외부 의견 details must not be open by default")
      .toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────
// Dashboard MarketActionCard surfaces NextDecisionChip (M15 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

test.describe("Dashboard surfaces the 'when' anchor (NextDecisionChip)", () => {
  // Previously the chip only rendered on /stocks/[ticker] and /screener.
  // Users landing on /dashboard could see "🟢 매수 우호" without any
  // indication of WHEN to act — book spirit is "Friday close decisions,
  // nothing on the other days." The chip now lives inside MarketActionCard
  // so the time anchor is right next to the macro verdict.
  test("dashboard renders the 다음 매매 결정 chip", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    await expect(body).toContainText("다음 매매 결정");
    await expect(body).toContainText("15:30 KST");
  });
});

// ─────────────────────────────────────────────────────────────────────
// /settings/alerts preset shortcuts (M17 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

test.describe("/settings/alerts has 3 preset shortcuts", () => {
  // 8 toggles with no entry point overwhelmed first-time users — either
  // everything-ON (telegram flood) or defaults-without-meaning. The 3
  // presets give a single-click answer (초보 / 책 정신 / 전체).
  test("renders all three presets visible at the top of the form", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/settings/alerts`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("[data-testid='preset-beginner']")).toBeVisible();
    await expect(page.locator("[data-testid='preset-book']")).toBeVisible();
    await expect(page.locator("[data-testid='preset-all']")).toBeVisible();
  });

  test("clicking 초보 preset turns ON enter / exit / disclosure", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/settings/alerts`, { waitUntil: "domcontentloaded" });
    await page.locator("[data-testid='preset-beginner']").click();
    // The 3 toggles 초보 preset turns ON. We don't assert the inverse
    // (other toggles OFF) here because the data-testid for checkboxes
    // can match mobile + desktop instances and strict-mode .not.toBeChecked
    // on multiple matches is flaky. The unit/snapshot test on the form
    // covers the OFF half via the React state shape directly.
    await expect(page.locator("[data-testid='pref-enable_enter']")).toBeChecked();
    await expect(page.locator("[data-testid='pref-enable_exit']")).toBeChecked();
    await expect(page.locator("[data-testid='pref-enable_disclosure']")).toBeChecked();
  });
});
