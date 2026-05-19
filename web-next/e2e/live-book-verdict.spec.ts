/**
 * Live BookVerdict smoke test.
 *
 * Opens /stocks/[ticker] in a real Chromium under an E2E auth session
 * and dumps the actual "한 줄 평" card body that renders for each
 * ticker. Asserts the verdict matches the analyzer intent after the
 * late-trend stretch gate (commits ec516f6 + f614f7b).
 *
 * Requires:
 *   - Next.js dev server running at $E2E_BASE_URL (default localhost:3000)
 *   - E2E_TEST_TOKEN set on both the test runner and the dev server
 *   - Supabase analyze_results rows for the 4 tickers reflect the new
 *     analyzer (we upserted them in the same commit chain).
 *
 * Skips gracefully when E2E_TEST_TOKEN is absent (CI without secrets).
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

async function signInAs(page: import("@playwright/test").Page, email: string) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email },
  });
  expect(r.ok(), `issue-session must succeed (got ${r.status()})`).toBe(true);
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

const TICKERS: Array<{
  ticker: string;
  /** Substring(s) that MUST appear in the rendered verdict card. */
  expect: RegExp[];
  /** Substring(s) that must NOT appear. */
  not?: RegExp[];
}> = [
  {
    ticker: "RKLB",
    expect: [
      /추세 유효 · 자리 지남/,
      /8주 \+115%/,
      /240MA 대비 \+\d+%/,
      /52w 위치 \d+%/,
      /마지막 캔들.*반전 주의/,
      /주봉 240MA.*벗어남/,
      /주봉 10MA.*이탈/,
    ],
    not: [/강한 매수/, /한 줄 평 · 관망/, /매복 · 포킹/],
  },
  {
    ticker: "GOOGL",
    expect: [
      /추세 유효 · 자리 지남/,
      /52w 위치 \d+%.*8주 \+45%/,
      /그레이브스톤도지.*반전 주의/,
      /주봉 10MA.*이탈/,
    ],
    not: [/한 줄 평 · 관망/, /매복 · 포킹/, /강한 매수/],
  },
  {
    ticker: "IONQ",
    expect: [
      /한 줄 평 · 관망/,
      /240MA.*죽지 않은/,
      /다음 결정 시점.*금요일/,
    ],
    not: [/자리 지남/, /강한 매수/, /매복 · 포킹/],
  },
  {
    ticker: "066620.KQ",
    expect: [/한 줄 평 · (매복 · 포킹 대기|강한 매수)/],
    not: [/자리 지남/, /한 줄 평 · 관망/, /회피/, /청산/],
  },
];

test.describe("Live BookVerdict per ticker", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");

  for (const t of TICKERS) {
    test(`/stocks/${t.ticker} renders the expected verdict`, async ({ page }) => {
      await signInAs(page, `verdict-${Date.now()}@e2e.test`);
      await page.goto(`/stocks/${encodeURIComponent(t.ticker)}`, {
        waitUntil: "domcontentloaded",
      });
      // BookVerdict is a server-rendered section keyed by "한 줄 평".
      const card = page.locator("section").filter({
        hasText: /한 줄 평/,
      }).first();
      await expect(card).toBeVisible({ timeout: 15_000 });
      const text = (await card.innerText()).trim();
      // Print to test runner stdout so we can read the actual content.
      // eslint-disable-next-line no-console
      console.log(`\n=== /stocks/${t.ticker} verdict card ===\n${text}\n`);
      for (const re of t.expect) {
        expect(text, `expected ${re} in ${t.ticker} card`).toMatch(re);
      }
      for (const re of t.not ?? []) {
        expect(text, `${re} should NOT appear in ${t.ticker} card`)
          .not.toMatch(re);
      }
    });
  }
});
