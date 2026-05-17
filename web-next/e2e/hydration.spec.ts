/**
 * Hydration smoke test — catches the kind of React 19 / Next 16 errors that
 * `npm run dev` printed (`Hydration failed`, `Encountered a script tag while
 * rendering React component`, hidden/data-* attribute mismatches).
 *
 * Strategy:
 *   1. Listen for console.error / pageerror BEFORE navigating.
 *   2. Visit each public page.
 *   3. Fail the test if any matching error fired.
 *
 * Browser extensions can inject DOM nodes and trigger spurious mismatches.
 * Playwright runs a clean Chromium without extensions, so any hydration
 * mismatch we see here is a real source-code bug.
 */
import { test, expect } from "@playwright/test";

const HYDRATION_NEEDLES = [
  "Hydration failed",
  "did not match",
  "Text content does not match server-rendered HTML",
  "Encountered a script tag while rendering React component",
];

function hookErrors(page: import("@playwright/test").Page): {
  consoleErrors: string[];
  pageErrors: string[];
} {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  return { consoleErrors, pageErrors };
}

function hydrationFailures(errors: string[]): string[] {
  return errors.filter((e) =>
    HYDRATION_NEEDLES.some((n) => e.toLowerCase().includes(n.toLowerCase())),
  );
}

const PUBLIC_PAGES = ["/login"];

for (const path of PUBLIC_PAGES) {
  test(`no hydration errors on ${path}`, async ({ page }) => {
    const { consoleErrors, pageErrors } = hookErrors(page);
    await page.goto(path, { waitUntil: "networkidle" });
    // Give React time to hydrate; some warnings fire post-commit.
    await page.waitForTimeout(500);

    const hydrationConsole = hydrationFailures(consoleErrors);
    const hydrationPage = hydrationFailures(pageErrors);
    expect(
      { hydrationConsole, hydrationPage },
      `Hydration errors on ${path}:\n  console: ${hydrationConsole.join("\n  ")}\n  page:    ${hydrationPage.join("\n  ")}`,
    ).toEqual({ hydrationConsole: [], hydrationPage: [] });
  });
}
