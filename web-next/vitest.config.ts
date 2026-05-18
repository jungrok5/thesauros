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
    environment: "node",
    include: ["src/**/__tests__/**/*.test.ts", "src/**/*.test.ts"],
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
  },
});
