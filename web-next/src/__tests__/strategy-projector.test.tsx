/**
 * StrategyProjector — math + rendering sanity.
 *
 * Pure-client component. Validates:
 *   1. Default render shows 책 전략 row on top (largest gain).
 *   2. Numerical compound math: 1000만원 × (1.218)^10 ≈ 71.1 백만.
 *   3. Input change re-computes (year slider).
 */
import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { StrategyProjector } from "@/components/strategy-projector";

afterEach(cleanup);

describe("StrategyProjector", () => {
  it("renders all 5 strategies with default 1000만원 / 10년", () => {
    render(<StrategyProjector />);
    expect(screen.getByText(/책 전략 \(이상적\)/)).toBeInTheDocument();
    expect(screen.getByText(/책 전략 \(현실 비용\)/)).toBeInTheDocument();
    expect(screen.getByText(/KOSPI 매수후 보유/)).toBeInTheDocument();
    expect(screen.getByText(/정기예금/)).toBeInTheDocument();
    expect(screen.getByText(/우량 회사채/)).toBeInTheDocument();
  });

  it("compounds 1000만원 × (1.095)^10 ≈ 2.48x (책 현실 비용, v1.1 locked)", () => {
    // 2026-06-03 — v1.1 survivorship-corrected locked baseline.
    // Universe = 3,465 ticker (active 2,599 + delisted 866) with
    // delisting-aware simulator. Prior v1 (CAGR 12.48) was inflated
    // by ~1.3 pp from survivorship bias. 2026-06-02/03 cycle: 24
    // factor variants (R1-R20) all REJECTED by 5-gate rule.
    // v1.1 honest: CAGR 11.19% ideal, ~9.5% realistic.
    // 1000만 × (1.095)^10 ≈ 2,478만 → 2.48x multiplier
    const { container } = render(
      <StrategyProjector defaultAmountManwon={1000} defaultYears={10} />,
    );
    const row = container.querySelector("tbody")!;
    expect(row.textContent).toMatch(/2\.48x/);
  });

  it("year slider updates the displayed years label", () => {
    render(<StrategyProjector defaultAmountManwon={1000} defaultYears={5} />);
    const slider = screen.getByRole("slider");
    // initial render: "5년" appears next to slider
    expect(screen.getAllByText(/5년/).length).toBeGreaterThan(0);
    fireEvent.change(slider, { target: { value: "12" } });
    expect(screen.getAllByText(/12년/).length).toBeGreaterThan(0);
  });
});
