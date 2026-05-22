/**
 * Tests for chart-vision rate limiter (회고 #28/#29).
 *
 * Vision API 비용 보호 — admin 1명 자동화 스크립트로 분당 100건 쏴도
 * 5건만 통과해야 함. 정상 사용 (분당 1-2 chart) 은 영향 없음.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  checkAndRecord,
  _resetForTests,
} from "@/lib/chart-vision-rate-limit";

beforeEach(() => {
  _resetForTests();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-22T00:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("chart-vision rate limiter", () => {
  it("allows first 5 hits per minute", () => {
    for (let i = 0; i < 5; i++) {
      const r = checkAndRecord("user-a");
      expect(r.ok, `hit ${i + 1} should pass`).toBe(true);
    }
  });

  it("blocks 6th hit within the same minute", () => {
    for (let i = 0; i < 5; i++) checkAndRecord("user-a");
    const r = checkAndRecord("user-a");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.window).toBe("minute");
      expect(r.retryAfterSec).toBeGreaterThan(0);
      expect(r.retryAfterSec).toBeLessThanOrEqual(60);
    }
  });

  it("isolates users — one user's overage doesn't block another", () => {
    for (let i = 0; i < 5; i++) checkAndRecord("user-a");
    const r = checkAndRecord("user-b");
    expect(r.ok).toBe(true);
  });

  it("resets the minute window after 60 seconds", () => {
    for (let i = 0; i < 5; i++) checkAndRecord("user-a");
    vi.advanceTimersByTime(60_001);   // just past the minute boundary
    const r = checkAndRecord("user-a");
    expect(r.ok).toBe(true);
  });

  it("enforces the hour window (30 hits)", () => {
    // Spread 30 hits across 6 minute windows so the per-minute limit
    // (5/min) doesn't trip first.
    for (let i = 0; i < 6; i++) {
      for (let j = 0; j < 5; j++) checkAndRecord("user-a");
      vi.advanceTimersByTime(60_001);
    }
    // We've now spent 30 hits over ~6 minutes — next one must be blocked
    // by the HOUR window (still inside 1 hour).
    const r = checkAndRecord("user-a");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.window).toBe("hour");
    }
  });

  it("does NOT record the hit when limit is exceeded", () => {
    // Fill the minute bucket.
    for (let i = 0; i < 5; i++) checkAndRecord("user-a");
    // Attempt 10 more — none should count toward the hour.
    for (let i = 0; i < 10; i++) checkAndRecord("user-a");
    // Wait 1 minute. Next minute window should allow exactly 5 more
    // (not 5 - 10).
    vi.advanceTimersByTime(60_001);
    let passed = 0;
    for (let i = 0; i < 10; i++) {
      if (checkAndRecord("user-a").ok) passed += 1;
    }
    expect(passed).toBe(5);
  });
});
