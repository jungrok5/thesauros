/**
 * DataFreshness chip — smoke + stale-threshold regression.
 *
 * Each cadence has a designated stale day count; the chip flips to amber
 * + adds a "N 갱신 지연" reason. Tests guard against accidental changes
 * to those thresholds (one missed cron should NOT flip a chip amber).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);

import { DataFreshness } from "@/components/data-freshness";

const NOW = new Date("2026-05-20T00:00:00Z");

function daysAgoIso(days: number): string {
  const d = new Date(NOW.getTime() - days * 86_400_000);
  return d.toISOString();
}

describe("DataFreshness chip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when asOf is null/undefined/invalid", () => {
    const { container: c1 } = render(<DataFreshness asOf={null} cadence="weekly" />);
    expect(c1).toBeEmptyDOMElement();
    cleanup();

    const { container: c2 } = render(<DataFreshness asOf={undefined} cadence="weekly" />);
    expect(c2).toBeEmptyDOMElement();
    cleanup();

    const { container: c3 } = render(<DataFreshness asOf="not-a-date" cadence="weekly" />);
    expect(c3).toBeEmptyDOMElement();
  });

  it("daily cadence: 3 days = fresh (green), 14 days = stale (amber)", () => {
    const { container: fresh } = render(
      <DataFreshness asOf={daysAgoIso(3)} cadence="daily" />,
    );
    expect(screen.getByText(/3일 전/)).toBeInTheDocument();
    expect(fresh.querySelector(".text-amber-700, .dark\\:text-amber-300")).toBeNull();
    expect(screen.queryByText(/지연/)).toBeNull();
    cleanup();

    render(<DataFreshness asOf={daysAgoIso(14)} cadence="daily" />);
    expect(screen.getByText(/2주 전/)).toBeInTheDocument();
    expect(screen.getByText(/일별 갱신.*지연/)).toBeInTheDocument();
  });

  it("weekly cadence: 10 days fresh, 21 days stale", () => {
    render(<DataFreshness asOf={daysAgoIso(10)} cadence="weekly" />);
    expect(screen.getByText(/10일 전/)).toBeInTheDocument();
    expect(screen.queryByText(/지연/)).toBeNull();
    cleanup();

    render(<DataFreshness asOf={daysAgoIso(21)} cadence="weekly" />);
    expect(screen.getByText(/주간 갱신.*지연/)).toBeInTheDocument();
  });

  it("quarterly cadence: 90d fresh, 180d stale", () => {
    render(<DataFreshness asOf={daysAgoIso(90)} cadence="quarterly" />);
    expect(screen.queryByText(/지연/)).toBeNull();
    cleanup();

    render(<DataFreshness asOf={daysAgoIso(180)} cadence="quarterly" />);
    expect(screen.getByText(/분기 갱신.*지연/)).toBeInTheDocument();
  });

  it("ageLabel produces human-friendly chunks (이번 주 / 어제 / N일 / N주 / N개월 / N년)", () => {
    render(<DataFreshness asOf={daysAgoIso(0)} cadence="daily" />);
    expect(screen.getByText(/이번 주/)).toBeInTheDocument();
    cleanup();
    render(<DataFreshness asOf={daysAgoIso(1)} cadence="daily" />);
    expect(screen.getByText(/어제/)).toBeInTheDocument();
    cleanup();
    render(<DataFreshness asOf={daysAgoIso(45)} cadence="quarterly" />);
    expect(screen.getByText(/6주 전/)).toBeInTheDocument();
    cleanup();
    render(<DataFreshness asOf={daysAgoIso(120)} cadence="yearly" />);
    expect(screen.getByText(/4개월 전/)).toBeInTheDocument();
    cleanup();
    render(<DataFreshness asOf={daysAgoIso(400)} cadence="yearly" />);
    expect(screen.getByText(/13개월 전/)).toBeInTheDocument();
  });

  it("future-stamped asOf (weekly bar that's the upcoming Friday) reads as '이번 주', not 'N일 후'", () => {
    render(<DataFreshness asOf={daysAgoIso(-2)} cadence="weekly" />);
    expect(screen.getByText(/이번 주/)).toBeInTheDocument();
    expect(screen.queryByText(/2일 후/)).toBeNull();
  });

  it("renders the YYYY-MM-DD prefix + custom label", () => {
    render(<DataFreshness asOf="2026-05-15" cadence="weekly" label="갱신" />);
    expect(screen.getByText(/2026-05-15 갱신/)).toBeInTheDocument();
  });
});

