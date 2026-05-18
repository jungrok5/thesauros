/**
 * Pattern freshness — how far has price moved past the breakout level?
 *
 * The pattern's `entry` field is filled with `last_close` whenever the
 * detector marks `completed=true`, so naively comparing entry against
 * current price always yields 0% runup. The TRUE breakout level lives
 * in `pattern.extra` (neckline / rim / ma_240 / ma_value).
 *
 * Used by the recommendations page and the stock-detail BookVerdict.
 * Extracted into a pure module so vitest can pin the buckets — earlier
 * regressions (using `entry` fallback) made YW + 슈프리마 + 삼지전자
 * appear as #1 on the fresh-sorted recommendations page.
 */

export interface FreshnessPatternInput {
  completed?: boolean;
  direction: "bullish" | "bearish" | "neutral";
  entry?: number | null;
  extra?: Record<string, unknown> | null;
  kind: string;
}

/** Breakout level from pattern.extra. Returns null if none available.
 *  For 장대양봉 catalyst patterns, we use the catalyst's close as the
 *  anchor — that's the level book treats as the new floor after the
 *  reversal event. */
export function breakoutLevel(p: FreshnessPatternInput): number | null {
  const ex = (p.extra ?? {}) as Record<string, unknown>;
  for (const c of [
    ex.neckline,
    ex.rim,
    ex.ma_240,
    ex.ma_value,
    ex.catalyst_close,
  ]) {
    if (typeof c === "number" && c > 0) return c;
  }
  return null;
}

/**
 * Bucket score for ranking: lower = better trading entry.
 *   0 : 0–5%       fresh breakout (right-now entry)
 *   1 : 5–15%      recent breakout, still chase-able
 *   2 : 15–30%     entry zone partly gone
 *   3 : -10–0%     pullback to breakout, may still be a valid entry
 *   4 : <-10%      broken below the pattern (invalidated)
 *   5 : >30%       long-gone breakout, stale
 */
export function bucketScore(runupPct: number): number {
  if (runupPct >= 0 && runupPct < 5) return 0;
  if (runupPct >= 5 && runupPct < 15) return 1;
  if (runupPct >= 15 && runupPct < 30) return 2;
  if (runupPct >= -10 && runupPct < 0) return 3;
  if (runupPct < -10) return 4;
  return 5;
}

export interface FreshnessResult {
  kind: string;
  breakout: number;
  runupPct: number;
}

/**
 * Pick the freshest completed bullish pattern from the list. "Freshest"
 * means the lowest bucket score; ties on bucket fall back to the lower
 * raw runup. Patterns without a breakout level in `extra` are skipped
 * (we can't tell where they broke out from), so a pattern array with
 * only `extra.bottoms` style patterns returns null.
 */
export function pickFreshest(
  patterns: FreshnessPatternInput[],
  lastClose: number,
): FreshnessResult | null {
  let best: FreshnessResult | null = null;
  for (const p of patterns) {
    if (!p.completed || p.direction !== "bullish") continue;
    const bl = breakoutLevel(p);
    if (bl == null) continue;
    const runup = (lastClose / bl - 1) * 100;
    if (best == null || bucketScore(runup) < bucketScore(best.runupPct)) {
      best = { kind: p.kind, breakout: bl, runupPct: runup };
    }
  }
  return best;
}

/** Latest 장대양봉 catalyst pattern. The page's HOLD narrative uses
 *  this to anchor "이미 +75% 위" type messages even when no chart
 *  pattern fired. */
export function pickCatalyst(
  patterns: FreshnessPatternInput[],
): FreshnessPatternInput | null {
  for (const p of patterns) {
    if (typeof p.kind === "string" && p.kind.includes("catalyst")) {
      return p;
    }
  }
  return null;
}

/**
 * Freshness multiplier — penalises stale patterns / amplifies entry-zone
 * patterns. Used as the second factor in the composite recommendation
 * score. Asymmetric: stale patterns punished hard (>30% runup → 5%),
 * pullback patterns lightly punished (still potentially valid), fresh
 * patterns full weight.
 *
 *   bucket 0  ( 0–5%   fresh        ) → 1.00
 *   bucket 1  ( 5–15%  chase-able   ) → 0.65
 *   bucket 2  ( 15–30% partial gone ) → 0.35
 *   bucket 3  (-10–0%  pullback     ) → 0.55
 *   bucket 4  ( <-10%  broken       ) → 0.10
 *   bucket 5  ( >30%   long gone    ) → 0.05
 *   null      (no breakout-level pattern available) → 0.50 (mild penalty
 *               so action-only signals don't dominate the leaderboard)
 */
export function freshnessMultiplier(runupPct: number | null): number {
  if (runupPct == null) return 0.5;
  const table = [1.0, 0.65, 0.35, 0.55, 0.1, 0.05];
  return table[bucketScore(runupPct)];
}

/**
 * Composite recommendation score: strength × freshnessMultiplier.
 *
 *   strength 0.91, fresh +3% → 0.91         (국보디자인-style)
 *   strength 0.91, chase +12% → 0.59        (YW-style)
 *   strength 0.91, stale +70% → 0.045       (SK텔레콤-style)
 *   strength 0.85, fresh +3% → 0.85         (lower strength but fresh)
 *   strength 0.91, no pattern info → 0.455  (action-only, conservative)
 *
 * This is the page's default sort key — surfaces tickers that are
 * BOTH high-conviction AND in a real entry zone, instead of forcing
 * the user to switch between strength and freshness sorts and mentally
 * combine them.
 */
export function compositeScore(strength: number, runupPct: number | null): number {
  return strength * freshnessMultiplier(runupPct);
}
