/**
 * Volume-surge helpers — detection threshold + 5-bucket interpretation.
 *
 * Regression guards against:
 *   - Sort direction (newest first) — wrong sort would pick the OLDEST
 *     week as "this week" and break everything downstream.
 *   - 2x surge threshold (don't fire on 1.9x — false positives are noisy).
 *   - 3x "강한" bucket — don't accidentally call 2.5x "강한 매집".
 *   - Price ±1.5% deadband — sideways gets the "🟤" bucket, not 매수/매도.
 *   - Insufficient data → silently skip (NOT throw, NOT emit garbage).
 */
import { describe, it, expect } from "vitest";
import {
  detectSurges,
  interpretSurge,
  fmtVol,
  type WeekBar,
} from "@/lib/volume-surge";

function makeBars(
  ticker: string,
  series: Array<{ date: string; close: number; volume: number }>,
): WeekBar[] {
  return series.map((s) => ({
    ticker,
    bar_date: s.date,
    close: s.close,
    volume: s.volume,
  }));
}

describe("detectSurges", () => {
  it("detects a 3x weekly volume surge with price spike", () => {
    // 9 weeks: oldest 8 weeks volume ~100, this week 400 → 4x
    const bars = makeBars("AAPL", [
      { date: "2026-05-15", close: 110, volume: 400 },  // this week
      { date: "2026-05-08", close: 100, volume: 100 },
      { date: "2026-05-01", close: 99, volume: 100 },
      { date: "2026-04-24", close: 100, volume: 100 },
      { date: "2026-04-17", close: 101, volume: 100 },
      { date: "2026-04-10", close: 100, volume: 100 },
      { date: "2026-04-03", close: 99, volume: 100 },
      { date: "2026-03-27", close: 100, volume: 100 },
      { date: "2026-03-20", close: 100, volume: 100 },
    ]);
    const out = detectSurges(bars);
    expect(out).toHaveLength(1);
    expect(out[0].ticker).toBe("AAPL");
    expect(out[0].ratio).toBeCloseTo(4, 5);
    expect(out[0].priceChangePct).toBeCloseTo(10, 5);
  });

  it("skips when ratio < 2x", () => {
    const bars = makeBars("AAPL", [
      { date: "2026-05-15", close: 110, volume: 190 },  // 1.9x
      { date: "2026-05-08", close: 100, volume: 100 },
      { date: "2026-05-01", close: 99, volume: 100 },
      { date: "2026-04-24", close: 100, volume: 100 },
      { date: "2026-04-17", close: 101, volume: 100 },
      { date: "2026-04-10", close: 100, volume: 100 },
    ]);
    expect(detectSurges(bars)).toEqual([]);
  });

  it("skips when history < 5 bars (data starvation)", () => {
    const bars = makeBars("AAPL", [
      { date: "2026-05-15", close: 110, volume: 500 },
      { date: "2026-05-08", close: 100, volume: 100 },
      { date: "2026-05-01", close: 99, volume: 100 },
    ]);
    expect(detectSurges(bars)).toEqual([]);
  });

  it("treats input order as unordered — sorts by date desc internally", () => {
    // SAME data as case 1 but in reverse order — should yield identical surge.
    const bars = makeBars("AAPL", [
      { date: "2026-03-20", close: 100, volume: 100 },
      { date: "2026-03-27", close: 100, volume: 100 },
      { date: "2026-04-03", close: 99, volume: 100 },
      { date: "2026-04-10", close: 100, volume: 100 },
      { date: "2026-04-17", close: 101, volume: 100 },
      { date: "2026-04-24", close: 100, volume: 100 },
      { date: "2026-05-01", close: 99, volume: 100 },
      { date: "2026-05-08", close: 100, volume: 100 },
      { date: "2026-05-15", close: 110, volume: 400 },
    ]);
    const out = detectSurges(bars);
    expect(out).toHaveLength(1);
    expect(out[0].ratio).toBeCloseTo(4, 5);
  });

  it("multi-ticker — sorts hits by ratio desc", () => {
    const a = makeBars("A", [
      { date: "2026-05-15", close: 110, volume: 400 },  // 4x
      ...Array.from({ length: 8 }, (_, i) => ({
        date: `2026-0${3 + Math.floor(i / 4)}-${10 - (i % 4)}`,
        close: 100,
        volume: 100,
      })),
    ]);
    const b = makeBars("B", [
      { date: "2026-05-15", close: 110, volume: 250 },  // 2.5x
      ...Array.from({ length: 8 }, (_, i) => ({
        date: `2026-0${3 + Math.floor(i / 4)}-${10 - (i % 4)}`,
        close: 100,
        volume: 100,
      })),
    ]);
    const out = detectSurges([...b, ...a]);
    expect(out.map((h) => h.ticker)).toEqual(["A", "B"]);
  });
});

describe("interpretSurge buckets", () => {
  const base = {
    ticker: "X",
    thisWeekVol: 1000,
    avgVol: 100,
    thisWeekClose: 100,
    prevWeekClose: 100,
  };

  it("price +5% + ratio 4x → 🟢 강한 매집", () => {
    const out = interpretSurge({ ...base, ratio: 4, priceChangePct: 5 });
    expect(out.label).toBe("🟢 강한 매집");
  });

  it("price +5% + ratio 2.5x → 🟡 매수 우위 (not 강한)", () => {
    const out = interpretSurge({ ...base, ratio: 2.5, priceChangePct: 5 });
    expect(out.label).toBe("🟡 매수 우위");
  });

  it("price -5% + ratio 4x → 🔴 강한 매도", () => {
    const out = interpretSurge({ ...base, ratio: 4, priceChangePct: -5 });
    expect(out.label).toBe("🔴 강한 매도");
  });

  it("price -3% + ratio 2.5x → 🟠 매도 우위", () => {
    const out = interpretSurge({ ...base, ratio: 2.5, priceChangePct: -3 });
    expect(out.label).toBe("🟠 매도 우위");
  });

  it("price +0.5% + ratio 4x → 🟤 횡보 (deadband)", () => {
    const out = interpretSurge({ ...base, ratio: 4, priceChangePct: 0.5 });
    expect(out.label).toBe("🟤 횡보 + 폭증");
  });

  it("price -1.0% + ratio 4x → 🟤 (still inside deadband)", () => {
    const out = interpretSurge({ ...base, ratio: 4, priceChangePct: -1.0 });
    expect(out.label).toBe("🟤 횡보 + 폭증");
  });
});

describe("fmtVol", () => {
  it("uses 억 / M / 만 thresholds", () => {
    expect(fmtVol(2.5e8)).toBe("2.5억");
    expect(fmtVol(3.4e6)).toBe("3.4M");
    expect(fmtVol(5e4)).toBe("5만");
    expect(fmtVol(123)).toBe("123");
  });
});
