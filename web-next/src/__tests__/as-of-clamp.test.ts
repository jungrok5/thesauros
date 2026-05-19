/**
 * Regression test for the "최종 종가 5월 22일" bug.
 *
 * Discovered 2026-05-19 — Naver labels in-progress weekly bars with
 * the Friday week-ending date, so mid-week (Tue) the latest bar
 * carries date=Friday, three days in the future. The bug was the
 * /api/quote handler returning that raw future date as `as_of`,
 * showing the user a 5월 22일 date on 5월 19일. `clampAsOfToToday`
 * fixes it; this test pins the behavior.
 */
import { describe, it, expect } from "vitest";
import { clampAsOfToToday } from "@/lib/as-of-clamp";

describe("clampAsOfToToday", () => {
  it("returns today when bar_date is in the future (the bug case)", () => {
    expect(clampAsOfToToday("2026-05-22", "2026-05-19")).toBe("2026-05-19");
  });

  it("returns bar_date when it's already in the past or today", () => {
    expect(clampAsOfToToday("2026-05-15", "2026-05-19")).toBe("2026-05-15");
    expect(clampAsOfToToday("2026-05-19", "2026-05-19")).toBe("2026-05-19");
  });

  it("clamps far-future dates too (defensive)", () => {
    // Hypothetical: bad ingest writes a 2027 bar. We shouldn't show
    // it as the "last close" date even if the price is real.
    expect(clampAsOfToToday("2027-01-01", "2026-05-19")).toBe("2026-05-19");
  });

  it("string comparison stays correct across year boundary", () => {
    // ISO-8601 dates sort lexicographically — sanity check that
    // a Jan-2026 bar_date doesn't accidentally compare > Dec-2025 in
    // some locale-dependent way.
    expect(clampAsOfToToday("2026-01-01", "2025-12-31")).toBe("2025-12-31");
    expect(clampAsOfToToday("2025-12-31", "2026-01-01")).toBe("2025-12-31");
  });
});
