/**
 * Verify the chip's label/style branches for each freshness zone.
 * The page-level surfaces (recommendations, themes, closing-trade) all
 * rely on this chip to communicate stale-vs-fresh — if a new zone
 * sneaks in or the thresholds change, the user-visible message must
 * still be coherent.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { FreshnessChip } from "@/components/freshness-chip";

describe("FreshnessChip", () => {
  it("renders '신선도 ?' when no pattern data", () => {
    render(<FreshnessChip fresh={null} />);
    expect(screen.getByText(/신선도 \?/)).toBeInTheDocument();
  });

  it("shows 🟢 신선 for 0-5% runup", () => {
    render(<FreshnessChip fresh={{ kind: "쌍바닥", runupPct: 3 }} />);
    expect(screen.getByText(/\+3% 🟢 신선/)).toBeInTheDocument();
  });

  it("shows 추격 가능 for 5-15% runup", () => {
    render(<FreshnessChip fresh={{ kind: "쌍바닥", runupPct: 12 }} />);
    expect(screen.getByText(/\+12% 추격 가능/)).toBeInTheDocument();
  });

  it("shows ⚠ 진입 자리 지남 for >30% runup (the SK텔레콤 case)", () => {
    render(<FreshnessChip fresh={{ kind: "역H&S", runupPct: 70 }} />);
    expect(screen.getByText(/\+70% ⚠ 진입 자리 지남/)).toBeInTheDocument();
  });

  it("shows 🔴 무효 가능 for <-10% runup", () => {
    render(<FreshnessChip fresh={{ kind: "쌍바닥", runupPct: -25 }} />);
    expect(screen.getByText(/-25% 🔴 무효 가능/)).toBeInTheDocument();
  });

  it("shows 풀백 for -10..0% runup", () => {
    render(<FreshnessChip fresh={{ kind: "쌍바닥", runupPct: -5 }} />);
    expect(screen.getByText(/-5% 풀백/)).toBeInTheDocument();
  });
});
