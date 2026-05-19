/**
 * Tests for market-aware stale detection.
 *
 * Without this, a KR ticker viewed at 19:00 KST on a weekday could
 * still show Monday's close on a Tuesday — the older 24h TTL hadn't
 * elapsed yet so the auto-dispatch didn't fire. We pin the calendar
 * math here so a future timezone refactor can't silently regress.
 */
import { describe, it, expect } from "vitest";
import {
  inferMarket,
  latestCompletedTradingDay,
  isAnalysisStale,
} from "@/lib/market-staleness";

// Helper: build a Date for a specific UTC wall-clock for deterministic
// tests; `now` is otherwise live and timezone-sensitive.
function utc(iso: string): Date {
  return new Date(`${iso}Z`);
}

describe("inferMarket", () => {
  it("recognizes KOSPI + KOSDAQ codes", () => {
    expect(inferMarket("005930.KS")).toBe("KR");
    expect(inferMarket("035420.KQ")).toBe("KR");
  });
  it("treats plain alpha tickers as US", () => {
    expect(inferMarket("AAPL")).toBe("US");
    expect(inferMarket("BRK.B")).toBe("US");
  });
  it("returns null for nonsense", () => {
    expect(inferMarket("")).toBe(null);
    expect(inferMarket("___")).toBe(null);
  });
});

describe("latestCompletedTradingDay (KR)", () => {
  it("returns today when past KST 16:00 on a weekday", () => {
    // Tuesday 2026-05-19 19:30 KST = 10:30 UTC.
    const now = utc("2026-05-19T10:30:00");
    expect(latestCompletedTradingDay("KR", now)).toBe("2026-05-19");
  });

  it("returns prior weekday before KST 16:00", () => {
    // Tuesday 2026-05-19 09:00 KST = 00:00 UTC — markets not yet closed.
    const now = utc("2026-05-19T00:00:00");
    expect(latestCompletedTradingDay("KR", now)).toBe("2026-05-18");
  });

  it("on Saturday returns the prior Friday", () => {
    // Saturday 2026-05-23 12:00 KST = 03:00 UTC.
    const now = utc("2026-05-23T03:00:00");
    expect(latestCompletedTradingDay("KR", now)).toBe("2026-05-22");
  });

  it("on Sunday returns the prior Friday", () => {
    // Sunday 2026-05-24 22:00 KST = 13:00 UTC.
    const now = utc("2026-05-24T13:00:00");
    expect(latestCompletedTradingDay("KR", now)).toBe("2026-05-22");
  });

  it("on Monday before 16:00 KST returns prior Friday", () => {
    // Monday 2026-05-18 10:00 KST = 01:00 UTC.
    const now = utc("2026-05-18T01:00:00");
    expect(latestCompletedTradingDay("KR", now)).toBe("2026-05-15");
  });
});

describe("isAnalysisStale (KR)", () => {
  // The exact scenario the user reported: Tue 19:30 KST, the analyzer
  // last ran at 14:18 KST today (before KRX close at 15:30). Today's
  // close has now settled but the cached analysis doesn't reflect it
  // → must be marked stale so the page auto-dispatches.
  it("KR: analyzer ran 14:18 KST, viewed 19:30 KST same day → stale", () => {
    const now = utc("2026-05-19T10:30:00"); // 19:30 KST
    const updated = utc("2026-05-19T05:18:36"); // 14:18 KST
    expect(isAnalysisStale("005930.KS", updated, now)).toBe(true);
  });

  it("KR: analyzer ran 17:00 KST (after close), viewed 20:00 KST → not stale", () => {
    const now = utc("2026-05-19T11:00:00"); // 20:00 KST
    const updated = utc("2026-05-19T08:00:00"); // 17:00 KST
    expect(isAnalysisStale("005930.KS", updated, now)).toBe(false);
  });

  it("KR: viewed Tue 10:00 KST during the session → yesterday's run is current", () => {
    const now = utc("2026-05-19T01:00:00"); // 10:00 KST
    const updated = utc("2026-05-18T08:00:00"); // Mon 17:00 KST
    expect(isAnalysisStale("005930.KS", updated, now)).toBe(false);
  });

  it("KR: weekend view with Friday-after-close analysis is fresh", () => {
    // Saturday 12:00 KST — Friday's 17:00 KST run still current.
    const now = utc("2026-05-23T03:00:00");
    const fridayRun = utc("2026-05-22T08:30:00"); // Fri 17:30 KST
    expect(isAnalysisStale("005930.KS", fridayRun, now)).toBe(false);
  });

  it("treats null/missing updatedAt as stale", () => {
    expect(isAnalysisStale("005930.KS", null)).toBe(true);
    expect(isAnalysisStale("005930.KS", undefined)).toBe(true);
    expect(isAnalysisStale("005930.KS", "not-a-date")).toBe(true);
  });

  it("treats unknown ticker shape as stale (safe-by-default)", () => {
    const now = utc("2026-05-19T10:00:00");
    expect(isAnalysisStale("$$$", utc("2026-05-19T08:00:00"), now)).toBe(true);
  });
});

describe("isAnalysisStale (US)", () => {
  it("US: analysis ran today during session, viewed before close → not stale", () => {
    // Tuesday 12:00 ET = 16:00 UTC, before 17:00 ET cutoff.
    const now = utc("2026-05-19T16:00:00");
    const updated = utc("2026-05-19T14:00:00");
    expect(isAnalysisStale("AAPL", updated, now)).toBe(false);
  });

  it("US: viewed past 17:00 ET cutoff with morning analysis → stale", () => {
    // Tuesday 23:00 UTC = 18:00 ET, past 17:00 ET cutoff. Analysis
    // last ran morning before market open.
    const now = utc("2026-05-19T23:00:00");
    const updated = utc("2026-05-19T13:00:00"); // 08:00 ET, pre-market
    expect(isAnalysisStale("AAPL", updated, now)).toBe(true);
  });
});
