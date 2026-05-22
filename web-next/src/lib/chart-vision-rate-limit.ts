/**
 * Per-user rate limiter for /api/chart-vision/analyze (회고 #28/#29).
 *
 * Vision API 비용: ~₩18 / 호출. admin 1명이 자동화 스크립트로 분당 100건
 * 쏘면 시간당 ~₩108k. Anthropic 의 per-minute throughput limit 도 trip.
 * 일반 user 까지 풀리면 (베타 종료 후) 위험 더 큼. 그 전에 가드.
 *
 * Algorithm: in-memory sliding window, per user-id.
 *   - 1분 window: 5건
 *   - 1시간 window: 30건
 *   - 1일 window: 200건
 * 둘 중 하나라도 초과면 429.
 *
 * 한계: Vercel serverless 의 cold-start 시 in-memory map 이 reset 됨.
 * 단일 instance 내 burst 차단엔 충분. Redis-backed limiter 가 필요하면
 * P_VISION_2 에서 Upstash 도입.
 *
 * Stateless route 와 호환 — 매 호출에서 map prune + check + record.
 */

type Window = { count: number; resetAt: number };

const buckets = new Map<string, { minute: Window; hour: Window; day: Window }>();

const LIMITS = {
  minute: { max: 5, windowMs: 60 * 1000 },
  hour: { max: 30, windowMs: 60 * 60 * 1000 },
  day: { max: 200, windowMs: 24 * 60 * 60 * 1000 },
};

export type RateLimitResult =
  | { ok: true }
  | { ok: false; window: "minute" | "hour" | "day"; retryAfterSec: number };

function tickWindow(w: Window, now: number, windowMs: number): Window {
  if (now >= w.resetAt) {
    return { count: 0, resetAt: now + windowMs };
  }
  return w;
}

/** Check and record a hit for `userId`. Returns rate-limit verdict. */
export function checkAndRecord(userId: string): RateLimitResult {
  const now = Date.now();
  let b = buckets.get(userId);
  if (!b) {
    b = {
      minute: { count: 0, resetAt: now + LIMITS.minute.windowMs },
      hour: { count: 0, resetAt: now + LIMITS.hour.windowMs },
      day: { count: 0, resetAt: now + LIMITS.day.windowMs },
    };
    buckets.set(userId, b);
  }
  b.minute = tickWindow(b.minute, now, LIMITS.minute.windowMs);
  b.hour = tickWindow(b.hour, now, LIMITS.hour.windowMs);
  b.day = tickWindow(b.day, now, LIMITS.day.windowMs);

  // Check BEFORE incrementing — if any window is already full, reject.
  if (b.day.count >= LIMITS.day.max) {
    return {
      ok: false,
      window: "day",
      retryAfterSec: Math.ceil((b.day.resetAt - now) / 1000),
    };
  }
  if (b.hour.count >= LIMITS.hour.max) {
    return {
      ok: false,
      window: "hour",
      retryAfterSec: Math.ceil((b.hour.resetAt - now) / 1000),
    };
  }
  if (b.minute.count >= LIMITS.minute.max) {
    return {
      ok: false,
      window: "minute",
      retryAfterSec: Math.ceil((b.minute.resetAt - now) / 1000),
    };
  }

  // Record the hit only after the check passed.
  b.minute.count += 1;
  b.hour.count += 1;
  b.day.count += 1;

  // Light periodic prune so the map doesn't grow unbounded across cold
  // boots. Buckets older than a day haven't been used recently.
  if (buckets.size > 1000) {
    for (const [k, v] of buckets) {
      if (v.day.resetAt < now) buckets.delete(k);
    }
  }

  return { ok: true };
}

/** Reset all in-memory state. Used by tests. */
export function _resetForTests(): void {
  buckets.clear();
}
