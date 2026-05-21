import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);

import { SubScoreChips } from "@/components/sub-score-chips";

describe("SubScoreChips", () => {
  it("renders nothing when all three inputs are null", () => {
    const { container } = render(
      <SubScoreChips volumeCase={null} quarterZone={null} catalystBarsSince={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows '바닥 폭증' chip for volume case 3", () => {
    render(<SubScoreChips volumeCase={3} />);
    expect(screen.getByText(/바닥 폭증/)).toBeInTheDocument();
  });

  it("shows '급등 폭증' chip for volume case 9", () => {
    render(<SubScoreChips volumeCase={9} />);
    expect(screen.getByText(/급등 폭증/)).toBeInTheDocument();
  });

  it("shows '매집 감소' for volume case 7/12 (bullish accumulation)", () => {
    render(<SubScoreChips volumeCase={7} />);
    expect(screen.getByText(/매집 감소/)).toBeInTheDocument();
    cleanup();
    render(<SubScoreChips volumeCase={12} />);
    expect(screen.getByText(/수렴 감소/)).toBeInTheDocument();
  });

  it("shows '분배 의심' for volume case 8 (bearish)", () => {
    render(<SubScoreChips volumeCase={8} />);
    expect(screen.getByText(/분배 의심/)).toBeInTheDocument();
  });

  it("renders safe75 / warn50 / danger25 / broken zone chips", () => {
    render(<SubScoreChips quarterZone="safe75" />);
    expect(screen.getByText(/safe75/)).toBeInTheDocument();
    cleanup();
    render(<SubScoreChips quarterZone="warn50" />);
    expect(screen.getByText(/warn50/)).toBeInTheDocument();
    cleanup();
    render(<SubScoreChips quarterZone="broken" />);
    expect(screen.getByText(/broken/)).toBeInTheDocument();
  });

  it("renders catalyst chip with weeks when bars_since <= 8", () => {
    render(<SubScoreChips catalystBarsSince={3} />);
    expect(screen.getByText(/catalyst-3w/)).toBeInTheDocument();
  });

  it("omits catalyst chip when bars_since > 8 (too stale)", () => {
    const { container } = render(<SubScoreChips catalystBarsSince={20} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("ignores unknown volume case numbers (no false chip)", () => {
    const { container } = render(<SubScoreChips volumeCase={99} />);
    expect(container).toBeEmptyDOMElement();
  });
});
