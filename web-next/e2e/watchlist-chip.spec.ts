/**
 * Live /watchlist chip smoke per ticker.
 *
 * The watchlist row chip pulls from `scan_results.signal_type` (latest
 * active `action_*` row), NOT from `analyze_results.action`. After the
 * stretch-gate fix (commits ec516f6 / f614f7b / 011f3d1), RKLB and
 * GOOGL became HOLD in analyze_results but their `action_buy` rows
 * in scan_results stayed `is_active=true` because the scan_daily cron
 * hadn't re-run. _action_signal() also dropped HOLD entirely. Net
 * effect: watchlist showed stale "매수" chips for both.
 *
 * The fix (this commit): _action_signal() emits `action_hold` when
 * the analyzer stamped a stretch_reason. This spec verifies that
 * after the cron sync (or our one-off DB upsert) the four tickers
 * render the expected chip.
 *
 * Requires E2E_TEST_TOKEN. Adds the 4 tickers to a throwaway test
 * account's watchlist, asserts chip text, then deletes them.
 */
import { test, expect } from "@playwright/test";

const E2E_TOKEN = process.env.E2E_TEST_TOKEN ?? "playwright-dev-only";

async function signInAs(page: import("@playwright/test").Page, email: string) {
  const r = await page.request.post("/api/e2e-test/issue-session", {
    headers: { "x-e2e-token": E2E_TOKEN },
    data: { email },
  });
  expect(r.ok()).toBe(true);
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

const EXPECT: Array<{
  ticker: string;
  /** chip text in the row (null = no chip rendered). */
  chip: string | null;
}> = [
  { ticker: "RKLB",       chip: "관망"     },
  { ticker: "GOOGL",      chip: "관망"     },
  { ticker: "IONQ",       chip: null       },
  { ticker: "066620.KQ",  chip: "강한 매수" },
];

test.describe("/watchlist action chip per ticker", () => {
  test.skip(!process.env.E2E_TEST_TOKEN, "set E2E_TEST_TOKEN to run");

  test("chips match analyzer state after stretch gate", async ({ page }) => {
    const email = `watchlist-chip-${Date.now()}@e2e.test`;
    await signInAs(page, email);

    // Seed the watchlist with the 4 tickers as observing.
    const created: string[] = [];
    for (const e of EXPECT) {
      const r = await page.request.post("/api/watchlist", {
        data: { ticker: e.ticker, category: "observing" },
      });
      // Some tickers (e.g. RKLB) may already be in the tickers master,
      // others need ensureTickerInMaster to insert. Either way we want
      // 2xx; surface any 5xx as a hard failure.
      if (r.status() >= 500) {
        throw new Error(
          `seed /api/watchlist failed for ${e.ticker}: ${r.status()} ${await r.text()}`,
        );
      }
      if (r.ok()) created.push(e.ticker);
    }

    try {
      await page.goto("/watchlist", { waitUntil: "domcontentloaded" });
      // Wait until at least one row is rendered (server-rendered).
      await expect(page.locator("li").first()).toBeVisible({ timeout: 15_000 });

      for (const e of EXPECT) {
        // Find the row containing the ticker text. The row-client uses
        // <Link href="/stocks/TICKER">...</Link> so the ticker is an
        // anchor inside the li.
        const row = page.locator("li", {
          has: page.locator(`a[href*="/stocks/${e.ticker}"]`),
        }).first();
        await expect(row).toBeVisible({ timeout: 5_000 });
        const txt = (await row.innerText()).trim();
        // eslint-disable-next-line no-console
        console.log(`\n=== /watchlist row for ${e.ticker} ===\n${txt}\n`);

        if (e.chip) {
          expect(txt, `${e.ticker} should show "${e.chip}" chip`)
            .toContain(e.chip);
          // And must NOT show the old stale chips.
          for (const stale of ["매수", "강한 매수", "매도", "회피"]) {
            if (stale === e.chip) continue;
            // "매수" is a substring of "강한 매수" — when expected is
            // "강한 매수" we skip the "매수" assertion to avoid false
            // positives.
            if (e.chip === "강한 매수" && stale === "매수") continue;
            expect(txt, `${e.ticker} must not show stale chip "${stale}"`)
              .not.toContain(stale);
          }
        }
      }
    } finally {
      // Always clean up to avoid polluting prod Supabase.
      for (const t of created) {
        await page.request.delete(
          `/api/watchlist?ticker=${encodeURIComponent(t)}`,
        );
      }
    }
  });
});
