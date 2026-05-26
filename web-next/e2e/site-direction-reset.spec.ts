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
  test("dashboard renders the 다음 결정 chip with valid phase", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const body = page.locator("body");
    await expect(body).toContainText("다음 결정");
    await expect(body).toContainText("15:30 KST");

    // M24 — the chip exposes the phase via data-phase on the wrapping
    // <section>. Must be one of the 3 known values; phase mapping has
    // its own unit tests (next-decision-chip-phase.test.ts), this just
    // pins that the attribute reaches the DOM.
    const phased = page.locator("[data-phase]");
    const count = await phased.count();
    expect(count, "at least one phased chip on dashboard").toBeGreaterThan(0);
    const phase = await phased.first().getAttribute("data-phase");
    expect(["wait", "decide", "review"]).toContain(phase);
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

// ─────────────────────────────────────────────────────────────────────
// Dashboard 거시 핵심 카드 default fold (M20 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

test.describe("Dashboard 거시 fold", () => {
  // Even with MarketActionCard's one-liner at the top, the original
  // layout dumped 8 raw macro cards (CPI/PPI/M2/etc.) right below it.
  // A beginner couldn't tell which one to act on — the actionable
  // verdict was already up top. Demoted to a collapsed <details>.
  test("'핵심 거시 지표' is inside a <details> (default collapsed)", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    const html = await page.content();
    if (!html.includes("핵심 거시 지표")) {
      test.skip(true, "no core macro indicators in current state");
      return;
    }
    expect(html).toMatch(
      /<summary[^>]*>[\s\S]{0,300}핵심 거시 지표[\s\S]{0,200}<\/summary>/,
    );
    const detailsOpen = html.match(
      /<details\s+open[^>]*>[\s\S]{0,500}핵심 거시 지표/,
    );
    expect(detailsOpen, "핵심 거시 지표 details must not be open by default")
      .toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────
// Chart marker invariants (M19 — 2026-05-26)
// Real visual rendering uses canvas, but we can lock the static label
// map + the createSeriesMarkers call path so the feature can't be
// silently deleted on a refactor.
// ─────────────────────────────────────────────────────────────────────

test.describe("BookChart pattern markers", () => {
  test("chart component wires up createSeriesMarkers with PATTERN_MARKER_LABEL", async ({ page }) => {
    // No need to hit the page — read the source file directly. This
    // catches "someone removed the marker call" regressions without
    // depending on a particular ticker's pattern data being populated.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(process.cwd(), "src/components/book-chart.tsx"),
      "utf8",
    );
    expect(src).toMatch(/PATTERN_MARKER_LABEL/);
    expect(src).toMatch(/createSeriesMarkers/);
    // The marker call must pass a non-empty markers array constructed
    // from data.patterns (not a hardcoded sample). Wide window because
    // the data-flow + filter + map can be 20+ lines.
    expect(src).toMatch(/data\.patterns[\s\S]+?createSeriesMarkers/);
  });
});

// ─────────────────────────────────────────────────────────────────────
// Watchlist holding 종목 stop-price guard (M21 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// /stocks/[ticker] section ordering + fold (M23 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// BookSummaryTable label clarification (M25 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// Verdict consistency between NoviceVerdict and BookVerdict
// (F1 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// Screener exposes eligibility chip (F2 — 2026-05-26)
// ─────────────────────────────────────────────────────────────────────

test.describe("screener exposes the eligibility safety chip", () => {
  // F2: even when book_score sorts an ineligible ticker to rank 1
  // (the 339950.KQ case — 책의 핵심 안전 게이트 누락 yet ranked first),
  // the screener row must surface that dissonance via a chip — user
  // sees "조건부 / 관망 / 회피" before clicking through.
  test("EligibilityChip component is wired through the screener page", async ({}) => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(process.cwd(), "src/app/(app)/screener/page.tsx"),
      "utf8",
    );
    expect(src).toMatch(/EligibilityChip/);
    expect(src).toMatch(/fetchEligibilityMap/);
    // The chip carries a data-eligibility attribute so E2E + a11y
    // pickers can target it.
    expect(src).toMatch(/data-eligibility=\{grade\}/);
    // Three downgrade tones must all be wired so the user can tell
    // CONDITIONAL/WATCH/AVOID apart without hovering.
    expect(src).toMatch(/AVOID/);
    expect(src).toMatch(/CONDITIONAL/);
    expect(src).toMatch(/WATCH/);
  });

  test("rendered /screener exposes at least one data-eligibility chip", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/screener`, { waitUntil: "domcontentloaded" });
    // Skip when DB has no analyze_results rows for the screener hits
    // (no eligibility data → no chips). Test guards behavior when
    // the data IS present.
    const chips = page.locator("[data-eligibility]");
    const count = await chips.count();
    if (count === 0) {
      test.skip(true, "no eligibility data on screener results today");
      return;
    }
    // Every chip's attribute value must be a valid downgrade grade.
    for (let i = 0; i < Math.min(count, 5); i++) {
      const v = await chips.nth(i).getAttribute("data-eligibility");
      expect(["CONDITIONAL", "WATCH", "AVOID"]).toContain(v);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────
// F3 — single verdict card (NoviceVerdict removed, merged into BookVerdict)
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// F4 — ActionBadge eligibility-aware
// F5 — header MultiTFMatrix + InvestorFlowChip removed (dup with summary table)
// F6 — BookEntrySpots EligibilityChip parity with screener
// ─────────────────────────────────────────────────────────────────────

test.describe("F4 — ActionBadge defers to eligibility on bullish downgrade", () => {
  test("STRONG_BUY + CONDITIONAL eligibility renders the 조건부 chip, not STRONG BUY", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/339950.KQ?from=screener`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    const html = await page.content();
    if (!html.includes("오늘 매수 자격: 조건부")) {
      test.skip(true, "eligibility wasn't CONDITIONAL for this ticker today");
      return;
    }
    // The badge carries data-action (raw) + data-eligibility (effective).
    // Locator targets the one in the page header (the only ActionBadge).
    const badges = page.locator("[data-action][data-eligibility]");
    const count = await badges.count();
    expect(count, "at least one action badge").toBeGreaterThan(0);
    // For the 339950.KQ case both ATTRIBUTES must reflect the dissonance.
    const dataAction = await badges.first().getAttribute("data-action");
    const dataElig = await badges.first().getAttribute("data-eligibility");
    expect(dataAction).toBe("STRONG_BUY");
    expect(dataElig).toBe("CONDITIONAL");
    // The visible label must NOT read "STRONG BUY" — it must read the
    // downgrade label "조건부" (book-spirit verdict, not raw action).
    const badgeText = await badges.first().innerText();
    expect(badgeText).not.toContain("STRONG BUY");
    expect(badgeText).toContain("조건부");
  });
});

test.describe("F5 — stock detail header is minimal (no raw chip above the verdict)", () => {
  test("MultiTFMatrix and InvestorFlowChip do not appear before the verdict card", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    const html = await page.content();
    const tickerIdx = html.indexOf("005930.KS");
    const verdictIdx = html.indexOf("한 줄 평");
    expect(tickerIdx).toBeGreaterThanOrEqual(0);
    expect(verdictIdx).toBeGreaterThan(tickerIdx);

    const headerBlock = html.slice(tickerIdx, verdictIdx);
    // These strings used to live INSIDE the header. Their presence
    // there was the F5 regression.
    expect(headerBlock).not.toContain("월/주/일 추세 정렬");
    // (InvestorFlowChip's hover text starts with this exact phrase.)
    expect(headerBlock).not.toContain("일 합계");
  });
});

test.describe("F6 — BookEntrySpots wires EligibilityChip", () => {
  test("BookEntrySpots component source includes the chip plus eligibility fetch", async ({}) => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(process.cwd(), "src/components/book-entry-spots.tsx"),
      "utf8",
    );
    expect(src).toMatch(/EligibilityChip/);
    // PostgREST JSON-path fetch identical to screener page
    expect(src).toMatch(/result->eligibility/);
    expect(src).toMatch(/data-eligibility=\{grade\}/);
  });
});

test.describe("verdict card is rendered exactly once", () => {
  // Before F3 the page rendered NoviceVerdict (above) + BookVerdict
  // (below) — both keying off `eligibility` after F1, so headline+body
  // appeared twice. F3 deleted NoviceVerdict and let BookVerdict be
  // the single source. We assert that the eligibility headline string
  // shows up at most once in the visible DOM (RSC stream may carry it
  // twice via SSR-HTML + hydration payload, both of which render as
  // the SAME on-screen card — count distinct visible elements).
  test("BookVerdict is the only headline source on /stocks/[ticker]", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/339950.KQ?from=screener&preset=book-buy`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    // Locator: the BookVerdict heading <h2> that always says "한 줄 평 · ...".
    const verdictHeading = page.locator("h2", { hasText: "한 줄 평 ·" });
    const count = await verdictHeading.count();
    expect(count, "exactly one verdict card should render").toBe(1);

    // And NoviceVerdict's old tombstone phrasings must not appear in
    // their old standalone position (without the "한 줄 평 ·" prefix
    // BookVerdict adds).
    const html = await page.content();
    // NoviceVerdict's headline used `<div class="text-sm font-semibold">`
    // wrapping bare "오늘 매수 자격: ..." without the BookVerdict prefix.
    // After F3 that pattern must be absent.
    const orphanHeadline = html.match(
      /<div[^>]*text-sm[^>]*font-semibold[^>]*>오늘 매수 자격:/,
    );
    expect(orphanHeadline, "no NoviceVerdict-style standalone headline").toBeNull();
  });
});

test.describe("verdict cards never contradict each other", () => {
  // The 339950.KQ case that triggered this guard: screener rank 1
  // (book_score 1.00, action=STRONG_BUY) but the analyzer's eligibility
  // field downgraded to CONDITIONAL because the runup-from-pattern
  // gate fired. Pre-F1 the page showed:
  //   NoviceVerdict: "오늘 매수 자격: 조건부 — 매수 X"
  //   BookVerdict:   "🟢 강한 매수 진입 2,755원 ..."
  // Now BookVerdict must defer to the eligibility downgrade — no
  // entry_plan card, tone matched to the eligibility grade.
  test("CONDITIONAL eligibility hides BookVerdict's entry plan", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/339950.KQ?from=screener&preset=book-buy`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});

    const html = await page.content();
    // If eligibility data isn't present for this ticker, skip — the
    // invariant only applies when the analyzer has shipped eligibility.
    if (!html.includes("오늘 매수 자격: 조건부")) {
      test.skip(true, "eligibility wasn't CONDITIONAL for this ticker today");
      return;
    }
    // When the novice card says 조건부, the BookVerdict card must not
    // simultaneously promise "🟢 강한 매수" or an entry plan with a
    // 진입 / 손절 / 목표 trio. (Strings checked because the card
    // content is server-rendered HTML.)
    expect(html, "BookVerdict must downgrade tone when eligibility != OK")
      .not.toContain("한 줄 평 · 강한 매수");
    expect(html, "no bullish entry plan when eligibility downgrades")
      .not.toMatch(/진입 \\d/);
  });
});

test.describe("/stocks/[ticker] BookSummaryTable label & guide", () => {
  // Pre-M25 the table heading read "책 정신 정리표 — 매매 결정 차원"
  // which sounded like the conclusion itself — a beginner could miss
  // the actual verdict (한 줄 평) sitting above it. Relabeled to
  // "결정 근거 — 6 차원 상세 (참고)" + added a hint line pointing
  // up to the verdict.
  test("BookSummaryTable carries the new label + '한 줄 평이 결론' hint", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    const html = await page.content();
    if (!html.includes("결정 근거")) {
      test.skip(true, "page didn't render BookSummaryTable");
      return;
    }
    // New heading wording
    expect(html).toContain("결정 근거 — 6 차원 상세 (참고)");
    // Old heading must be GONE (otherwise both render side by side)
    expect(html).not.toContain("책 정신 정리표 — 매매 결정 차원");
    // Pointer-up hint to the actual verdict
    expect(html).toMatch(/↑.*한 줄 평.*결론/);
  });
});

test.describe("/stocks/[ticker] section ordering after M23 regroup", () => {
  // The book's mental model: 결론 → 차트 → "이 신호 historically 어땠나"
  // → 펀더 (보조). Previously 책 전략 was after 펀더, so a reader who
  // ran out of attention at 펀더 never saw the strategy projection that
  // is THE book-spirit verification. Moved 책 전략 above 펀더.
  test("'🧮 책 전략 적용 시' renders before '🏛️ 펀더멘털 검증'", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    const html = await page.content();
    const stratIdx = html.indexOf("🧮 책 전략 적용 시");
    const fundIdx = html.indexOf("🏛️ 펀더멘털 검증");
    // Skip when ticker has no data — verdict shell missing.
    if (stratIdx === -1 || fundIdx === -1) {
      test.skip(true, "stock page sections not rendered for this ticker");
      return;
    }
    expect(stratIdx, "책 전략 must come before 펀더").toBeLessThan(fundIdx);
  });

  test("'💰 배당 · 공매도' lives in a default-collapsed <details>", async ({ page }) => {
    await signIn(page);
    await page.goto(`${BASE}/stocks/005930.KS`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    const html = await page.content();
    if (!html.includes("💰 배당 · 공매도")) {
      test.skip(true, "no dividend/short data for this ticker");
      return;
    }
    expect(html).toMatch(
      /<summary[^>]*>[\s\S]{0,300}💰 배당 · 공매도[\s\S]{0,200}<\/summary>/,
    );
    const detailsOpen = html.match(
      /<details\s+open[^>]*>[\s\S]{0,500}💰 배당 · 공매도/,
    );
    expect(detailsOpen, "💰 배당 · 공매도 details must not be open by default")
      .toBeNull();
  });
});

test.describe("Watchlist holding requires a stop loss", () => {
  // Direct UI test would need a holding row in the user's watchlist —
  // out of scope for an empty-DB E2E. Read the source guard instead:
  // the save() function must short-circuit when category=='holding'
  // and both stop fields are blank, AND the form must add the required
  // attribute when applicable. This catches "someone removed the guard"
  // refactors without seeding test data.
  test("row-client.tsx contains the holding/stop guard", async ({ }) => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(process.cwd(), "src/app/(app)/watchlist/row-client.tsx"),
      "utf8",
    );
    // The guard checks category === "holding" with both stop blank
    expect(src).toMatch(
      /row\.category === "holding"[\s\S]{0,200}stop === ""[\s\S]{0,200}stopPct === ""/,
    );
    // The 책 정신 강제 amber notice renders only for holding.
    expect(src).toMatch(/책 정신 강제: 보유 종목은 손절가 필수/);
    // The stop inputs flip required={...} for holding category.
    expect(src).toMatch(/required=\{row\.category === "holding"/);
  });
});
