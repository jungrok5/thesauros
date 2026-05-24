/**
 * TickerSignalHistory — server component that loads per-ticker JSON
 * stats and renders a table.
 *
 * Validates:
 *   1. Renders "데이터 없음" fallback when JSON is missing.
 *   2. Renders signal rows when JSON is present.
 *   3. SL policy chips ("ON 권장" / "OFF 권장" / "중립") match per-signal table.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Stub fs/promises BEFORE the component imports it (server component).
vi.mock("node:fs/promises", () => ({
  default: {
    readFile: vi.fn(),
  },
}));

import fs from "node:fs/promises";

beforeEach(() => {
  // Reset the module to clear the in-process STATS_CACHE between tests.
  vi.resetModules();
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("TickerSignalHistory", () => {
  it("renders fallback when ticker has no entry in stats JSON", async () => {
    // Master JSON loads but lacks our ticker
    (fs.readFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      JSON.stringify({ "OTHER.KS": { action_buy: { n: 5, avg_pct: 1, win_pct: 50, median_pct: 0 } } }),
    );
    const mod = await import("@/components/ticker-signal-history");
    const view = await mod.TickerSignalHistory({ ticker: "ZZZZZ.KS" });
    render(view);
    expect(screen.getByText(/책 신호 3회 이상 발생한 적이 없습니다/))
      .toBeInTheDocument();
  });

  it("renders signal rows + SL policy chips", async () => {
    const fixture = {
      "005930.KS": {
        volume_case_3: { n: 8, avg_pct: 12.5, win_pct: 75, median_pct: 10.0 },
        action_buy: { n: 12, avg_pct: 3.2, win_pct: 50, median_pct: 2.1 },
      },
    };
    (fs.readFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      JSON.stringify(fixture),
    );
    const mod = await import("@/components/ticker-signal-history");
    const view = await mod.TickerSignalHistory({ ticker: "005930.KS" });
    const { container } = render(view);
    // Raw keys appear in the (sig) tooltip span
    expect(container.textContent).toContain("volume_case_3");
    expect(container.textContent).toContain("action_buy");
    // "ON 권장" appears in chip + footer; OFF 권장 in chip only
    expect(screen.getAllByText(/ON 권장/).length).toBeGreaterThan(0);
    expect(screen.getByText(/OFF 권장/)).toBeInTheDocument();
  });
});
