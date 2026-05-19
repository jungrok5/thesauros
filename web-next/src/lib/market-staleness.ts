/**
 * Market-aware staleness detection for cached analyses.
 *
 * The fixed 24-hour TTL used previously was too coarse — a user opening
 * a KR stock page at 19:00 KST would see Monday's close on a Tuesday
 * (today's close already settled at 15:30 KST + a margin) because the
 * 24h window hadn't elapsed since the morning. Now we compare the
 * cached `as_of` against the *expected* latest completed trading day
 * for the ticker's market and dispatch a fresh ingest when behind.
 *
 * KR (KOSPI/KOSDAQ): KRX closes 15:30 KST. Naver Finance's frgn page
 * (investor flow) needs ~1 hour after close to fully populate, so we
 * treat 16:00 KST as the "today is fresh" cutoff. Weekdays only — we
 * don't currently track holidays; on a 추석/설 the worst case is one
 * extra dispatch that just no-ops.
 *
 * US: NYSE/NASDAQ close 16:00 ET. Yahoo's chart endpoint is current
 * within minutes of close, so we treat 17:00 ET (~01:00 KST next day,
 * give or take DST) as the cutoff. Same weekday-only assumption.
 *
 * Both helpers return `YYYY-MM-DD` strings; callers compare with
 * `as_of` lexicographically (safe — ISO-8601 dates sort correctly).
 */

const KR_MARKETS = /^[0-9]{6}\.(KS|KQ)$/;
const US_MARKET_HINTS = /^[A-Z][A-Z0-9.\-]{0,15}$/;

export type Market = "KR" | "US";

export function inferMarket(ticker: string): Market | null {
  if (KR_MARKETS.test(ticker)) return "KR";
  if (US_MARKET_HINTS.test(ticker)) return "US";
  return null;
}

/**
 * Most recent completed trading day for a given market, as YYYY-MM-DD
 * in the market's local timezone. If now is past the cutoff and today
 * is a weekday, today qualifies; otherwise the prior weekday.
 */
export function latestCompletedTradingDay(
  market: Market,
  now: Date = new Date(),
): string {
  const tz = market === "KR" ? "Asia/Seoul" : "America/New_York";
  const cutoffHourLocal = market === "KR" ? 16 : 17;

  const localHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hour: "numeric",
      hour12: false,
    }).format(now),
  );
  const isPastCutoff = localHour >= cutoffHourLocal;

  // Walk back day-by-day in market-local time. Start at "today" (in
  // market tz). If past cutoff and weekday → today. Otherwise walk
  // back to most recent weekday.
  const todayIso = isoDateInTz(now, tz);
  const startOffset = isPastCutoff ? 0 : 1;
  for (let offset = startOffset; offset < 8; offset++) {
    const candidate = addDaysIso(todayIso, -offset);
    if (isWeekday(candidate)) return candidate;
  }
  // Pathological fallback — never reached in practice.
  return todayIso;
}

/**
 * True when the cached analysis is older than the latest market-close
 * cutoff that produced new data. The signal is the analyzer's run
 * timestamp (`analyze_results.updated_at`) — NOT the embedded `as_of`,
 * which is the underlying bar's date and stays stable across re-runs.
 *
 * KR rule: if `now` is past 16:00 KST on a weekday AND `updatedAt`
 * predates today's 16:00 KST, the cache missed today's settlement.
 * Outside trading hours (weekend, before 16:00) any cache from after
 * the last weekday's 16:00 is current.
 *
 * US mirrors with 17:00 ET. The 1-hour buffer after each market close
 * absorbs Naver/Yahoo publish lag.
 *
 * Anything we can't classify (unknown market, missing updatedAt) is
 * treated as stale so the caller dispatches a refresh.
 */
export function isAnalysisStale(
  ticker: string,
  updatedAt: string | Date | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!updatedAt) return true;
  const market = inferMarket(ticker);
  if (!market) return true;
  const updatedDate =
    typeof updatedAt === "string" ? new Date(updatedAt) : updatedAt;
  if (!(updatedDate instanceof Date) || isNaN(updatedDate.getTime())) {
    return true;
  }
  const expectedCutoff = latestCompletedTradingCutoff(market, now);
  return updatedDate.getTime() < expectedCutoff.getTime();
}

/**
 * The market-close cutoff (UTC instant) corresponding to the latest
 * settlement the cache should reflect. If `now` is past today's cutoff
 * on a weekday, that's today's; otherwise the prior weekday's.
 *
 * KR has no DST so 16:00 KST = 07:00 UTC year-round.
 * US 17:00 ET swings between 21:00 UTC (EDT, summer) and 22:00 UTC
 * (EST, winter). We use the later 22:00 UTC as a safe upper bound —
 * the worst case is one extra hour of "non-stale" status during EDT,
 * never a false stale signal that fires before market actually closed.
 *
 * Exported for unit tests that want to assert specific instants.
 */
export function latestCompletedTradingCutoff(
  market: Market,
  now: Date = new Date(),
): Date {
  const day = latestCompletedTradingDay(market, now);
  if (market === "KR") return new Date(`${day}T07:00:00Z`);
  return new Date(`${day}T22:00:00Z`);
}

// ─────────────────────────────────────────────────────────────────────
// helpers
// ─────────────────────────────────────────────────────────────────────

function isoDateInTz(date: Date, tz: string): string {
  // en-CA produces "YYYY-MM-DD" formatting — convenient.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function addDaysIso(iso: string, deltaDays: number): string {
  // Treat the YYYY-MM-DD as a UTC date so deltaDays arithmetic is
  // timezone-free; we only need calendar-day math.
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + deltaDays);
  return dt.toISOString().slice(0, 10);
}

function isWeekday(iso: string): boolean {
  const [y, m, d] = iso.split("-").map(Number);
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return dow >= 1 && dow <= 5;
}
