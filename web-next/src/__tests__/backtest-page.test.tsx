/**
 * /backtest page — renders summary stats + equity curve from the
 * precomputed JSON.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("node:fs/promises", () => ({
  default: { readFile: vi.fn() },
}));

import fs from "node:fs/promises";

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});
afterEach(() => cleanup());

const fixture = {
  config: "SL=10% / max=8 / 24w / top-5",
  start: "2009-01-02",
  end: "2026-05-22",
  initial: 10_000_000,
  final: 647_977_910,
  summary: {
    total_return_pct: 6380.27,
    annualised_return_pct: 27.02,
    max_drawdown_pct: 37.07,
    sharpe: 0.821,
    sortino: 1.501,
    calmar: 0.729,
    alpha_annual_pct: 19.33,
    beta: 0.664,
    r_squared: 0.147,
    kospi_ann_ret_pct: 11.48,
    outperformance_ann_pct: 15.53,
  },
  weekly: [
    { d: "2009-01-02", e: 10_000_000 },
    { d: "2010-01-01", e: 12_000_000 },
    { d: "2026-05-22", e: 647_977_910 },
  ],
};

describe("/backtest page", () => {
  it("renders headline stats from the equity JSON", async () => {
    (fs.readFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      JSON.stringify(fixture),
    );
    // dynamic import after mock
    const mod = await import("@/app/(app)/backtest/page");
    const view = await mod.default();
    render(view);
    expect(screen.getByText(/총 수익률/)).toBeInTheDocument();
    // Fixture's total = 6380; may appear in both headline + methodology note
    expect(screen.getAllByText(/\+6380%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Sharpe/).length).toBeGreaterThan(0);
    expect(screen.getByText(/0\.82/)).toBeInTheDocument();
    expect(screen.getByText(/Max DD/)).toBeInTheDocument();
    expect(screen.getByText(/책 전략 17년 백테스트/)).toBeInTheDocument();
  });

  it("shows fallback when JSON missing", async () => {
    (fs.readFile as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("ENOENT"),
    );
    const mod = await import("@/app/(app)/backtest/page");
    const view = await mod.default();
    render(view);
    expect(screen.getByText(/equity-production\.json 이 누락/)).toBeInTheDocument();
  });
});
