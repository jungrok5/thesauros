import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E tests for Thesauros.
 *
 * Assumes both servers are already running:
 *   FastAPI : http://127.0.0.1:8001
 *   Next.js : http://localhost:3000
 *
 * Tests assume signed-out state for the public flow and use mocked
 * session cookies for the authed flow.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
