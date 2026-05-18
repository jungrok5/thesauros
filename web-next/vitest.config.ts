import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * Vitest config for fast, no-browser unit tests of pure helpers and
 * library logic. Playwright stays for browser-level E2E. Vitest covers
 * everything else — recommendation scoring, signal labels, freshness
 * buckets, sanitizers, etc.
 *
 * Tests live next to the code under `__tests__/` or as `*.test.ts`.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    // jsdom needed for component-render tests (FreshnessChip etc.) —
    // pure logic tests don't care which environment they run in.
    environment: "jsdom",
    include: ["src/**/__tests__/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
  },
});
