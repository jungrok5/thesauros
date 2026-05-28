/**
 * In-memory per-instance rate limiter for API routes.
 *
 * Sized for a small Vercel deployment (1-2 instances). NOT distributed
 * — each function instance keeps its own bucket; total throttle is
 * `limit × instances`. Good enough for "stop one user from hammering
 * Yahoo/Naver in a loop" but not a hard guarantee.
 *
 * Usage:
 *   import { rateLimit } from "@/lib/rate-limit";
 *   const limited = rateLimit(`news:${userKey}`, { limit: 30, windowMs: 60_000 });
 *   if (limited) return NextResponse.json({ error: "rate_limited" }, { status: 429 });
 */

interface Bucket {
  count: number;
  resetAt: number;
}

const _BUCKETS = new Map<string, Bucket>();
const _MAX_KEYS = 5000;   // hard cap so a runaway key flood can't grow forever

export interface RateLimitOptions {
  /** Max requests allowed per `windowMs`. */
  limit: number;
  /** Rolling window length in milliseconds. */
  windowMs: number;
}

/**
 * Returns true when the request EXCEEDS the limit (caller should 429).
 * Returns false when allowed (caller proceeds).
 *
 * The bucket key should encode whatever scope you want to throttle —
 * typical patterns: `${route}:${userId}` or `${route}:${ip}` or
 * `${route}` for a per-route global cap.
 */
export function rateLimit(key: string, opts: RateLimitOptions): boolean {
  const now = Date.now();
  // Defensive map cleanup — drop stale buckets when we hit the cap.
  if (_BUCKETS.size >= _MAX_KEYS) {
    for (const [k, b] of _BUCKETS) {
      if (b.resetAt <= now) _BUCKETS.delete(k);
      if (_BUCKETS.size < _MAX_KEYS * 0.8) break;
    }
  }
  const bucket = _BUCKETS.get(key);
  if (!bucket || bucket.resetAt <= now) {
    _BUCKETS.set(key, { count: 1, resetAt: now + opts.windowMs });
    return false;
  }
  bucket.count += 1;
  if (bucket.count > opts.limit) return true;
  return false;
}
