/**
 * Flow ranking helpers — aggregation + KRW formatting.
 *
 * Regression guards against:
 *   - PostgREST returning numeric values as STRINGS ("1234") not numbers.
 *     Bug we want to lock down: `Number("123") + Number("456")` works but
 *     a raw `"123" + "456"` would silently concat into "123456".
 *   - Null / undefined coercion to 0 (some old rows have null institution).
 *   - Sort direction (buy = desc, sell = asc) — easy to flip by accident.
 *   - 조 / 억 / 만 threshold formatting matching the dashboard's other widgets.
 */
import { describe, it, expect } from "vitest";
import {
  aggregateFlowRows,
  sortAndTake,
  fmtKRW,
  type RawFlowRow,
} from "@/lib/flow-aggregate";

describe("aggregateFlowRows", () => {
  it("sums numeric foreign + institution across multiple days", () => {
    const rows: RawFlowRow[] = [
      { ticker: "005930.KS", day: "2026-05-19", foreign_net: 100, institution_net: 50 },
      { ticker: "005930.KS", day: "2026-05-18", foreign_net: 200, institution_net: -30 },
      { ticker: "000660.KS", day: "2026-05-19", foreign_net: -50, institution_net: 10 },
    ];
    const out = aggregateFlowRows(rows);
    const samsung = out.find((r) => r.ticker === "005930.KS")!;
    expect(samsung.foreign_sum).toBe(300);
    expect(samsung.institution_sum).toBe(20);
    expect(samsung.combined_sum).toBe(320);
    expect(samsung.days).toBe(2);
  });

  it("coerces string-typed numbers (PostgREST numeric → string) correctly", () => {
    // PostgREST returns numeric columns as JS strings. If we forget
    // Number() the addition would concatenate strings → garbage.
    const rows: RawFlowRow[] = [
      { ticker: "005930.KS", day: "2026-05-19", foreign_net: "100", institution_net: "50" },
      { ticker: "005930.KS", day: "2026-05-18", foreign_net: "200", institution_net: "30" },
    ];
    const out = aggregateFlowRows(rows);
    expect(out[0].foreign_sum).toBe(300);
    expect(out[0].institution_sum).toBe(80);
  });

  it("treats null net values as 0 (not NaN)", () => {
    const rows: RawFlowRow[] = [
      { ticker: "005930.KS", day: "2026-05-19", foreign_net: null, institution_net: 50 },
      { ticker: "005930.KS", day: "2026-05-18", foreign_net: 100, institution_net: null },
    ];
    const out = aggregateFlowRows(rows);
    expect(out[0].foreign_sum).toBe(100);
    expect(out[0].institution_sum).toBe(50);
    expect(Number.isNaN(out[0].combined_sum)).toBe(false);
  });

  it("returns empty array on empty input", () => {
    expect(aggregateFlowRows([])).toEqual([]);
  });
});

describe("sortAndTake", () => {
  const rows = [
    { ticker: "A", foreign_sum: 0, institution_sum: 0, combined_sum: 100, days: 1 },
    { ticker: "B", foreign_sum: 0, institution_sum: 0, combined_sum: -50, days: 1 },
    { ticker: "C", foreign_sum: 0, institution_sum: 0, combined_sum: 300, days: 1 },
    { ticker: "D", foreign_sum: 0, institution_sum: 0, combined_sum: -200, days: 1 },
  ];

  it("buy direction returns highest combined first", () => {
    const out = sortAndTake(rows, "buy", 2);
    expect(out.map((r) => r.ticker)).toEqual(["C", "A"]);
  });

  it("sell direction returns lowest combined first", () => {
    const out = sortAndTake(rows, "sell", 2);
    expect(out.map((r) => r.ticker)).toEqual(["D", "B"]);
  });

  it("respects limit", () => {
    expect(sortAndTake(rows, "buy", 100).length).toBe(4);
    expect(sortAndTake(rows, "buy", 1).length).toBe(1);
  });
});

describe("fmtKRW", () => {
  it("formats 조 / 억 / 만 thresholds", () => {
    expect(fmtKRW(1.5e12)).toBe("1.5조");
    expect(fmtKRW(2.5e8)).toBe("3억");
    expect(fmtKRW(1.5e4)).toBe("2만");
    expect(fmtKRW(0)).toBe("0");
  });

  it("preserves sign for negatives (the matters for sell flow)", () => {
    expect(fmtKRW(-3e8)).toBe("-3억");
    expect(fmtKRW(-1.2e12)).toBe("-1.2조");
  });
});
