import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);

import { RowSparkline } from "@/components/row-sparkline";

describe("RowSparkline", () => {
  it("renders nothing when series is null / too short", () => {
    const { container: c1 } = render(<RowSparkline series={null} />);
    expect(c1).toBeEmptyDOMElement();
    cleanup();
    const { container: c2 } = render(<RowSparkline series={[]} />);
    expect(c2).toBeEmptyDOMElement();
    cleanup();
    const { container: c3 } = render(<RowSparkline series={[100]} />);
    expect(c3).toBeEmptyDOMElement();
  });

  it("uses emerald stroke when last >= first (up trend)", () => {
    const { container } = render(<RowSparkline series={[100, 101, 99, 110]} />);
    const poly = container.querySelector("polyline");
    expect(poly?.getAttribute("class")).toContain("emerald");
  });

  it("uses rose stroke when last < first (down trend)", () => {
    const { container } = render(<RowSparkline series={[110, 108, 95]} />);
    const poly = container.querySelector("polyline");
    expect(poly?.getAttribute("class")).toContain("rose");
  });

  it("flat series renders without div-by-zero crash", () => {
    const { container } = render(<RowSparkline series={[100, 100, 100, 100]} />);
    const poly = container.querySelector("polyline");
    expect(poly).toBeTruthy();
    expect(poly?.getAttribute("points")).toBeTruthy();
  });

  it("draws N points for a series of length N", () => {
    const { container } = render(<RowSparkline series={[1, 2, 3, 4, 5]} />);
    const poly = container.querySelector("polyline");
    const points = (poly?.getAttribute("points") ?? "").split(/\s+/).filter(Boolean);
    expect(points.length).toBe(5);
  });
});
