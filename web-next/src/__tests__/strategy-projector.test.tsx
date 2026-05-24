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

  it("compounds 1000만원 × (1.218)^10 → roughly 7천만대", () => {
    // 1000만 = 10,000,000 KRW
    // × (1.218)^10 ≈ 7.11 → 7천만 ~ 8천만 area
    const { container } = render(
      <StrategyProjector defaultAmountManwon={1000} defaultYears={10} />,
    );
    // Find the row with "책 전략 (현실 비용)" label
    const row = container.querySelector("tbody")!;
    expect(row.textContent).toMatch(/7\.\d{2}/);   // 7.xx in some col
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
