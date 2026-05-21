/**
 * Market-session helpers — was this `asOf` date a CONFIRMED close, or
 * an in-progress intraday quote?
 *
 * Why this exists: /api/quote/[ticker] returns the latest available bar
 * — which on a Monday at 11:00 KST is *today's in-progress bar*, not
 * yesterday's confirmed close. Displaying that as "최종 종가 (2026-05-21)"
 * is wrong (the day's high/low/close are still moving). This module
 * gives `priceLabelFor(ticker, asOf)` so every callsite agrees.
 *
 * The bug has been re-introduced 3 times (commits 4956455, 0d7d926,
 * ae076ef) — hence the explicit, well-tested module instead of inline
 * if-blocks. See `market-session.test.ts` for the regression battery.
 *
 * Cutoffs (intraday → confirmed):
 *   KR (.KS/.KQ)   15:30 KST  — KRX regular close
 *   US (otherwise) 16:00 ET   — NYSE/NASDAQ close
 *
 * Both add a small post-close buffer for upstream (Naver/Yahoo) to mark
 * the bar as final. Within `[cutoff, cutoff + 30min)` we still call it
 * "intraday" to be safe.
 */

export type MarketSession =
  | "intraday"   // 오늘 + 마감 전 (또는 마감 직후 30분 buffer 안) — 가격 변동 중
  | "closed"     // 오늘 + 마감 + buffer 후 — 종가 확정
  | "stale";     // asOf 가 오늘이 아님 — 지난 영업일/주말 종가

export function marketTimezone(ticker: string): "Asia/Seoul" | "America/New_York" {
  return /\.(KS|KQ)$/i.test(ticker) ? "Asia/Seoul" : "America/New_York";
}

/** Cutoff in market-local minutes-since-midnight + a 30 min upstream
 *  buffer. KR 15:30 + 30 = 16:00; US 16:00 + 30 = 16:30. */
function cutoffMinutes(ticker: string): number {
  const isKr = /\.(KS|KQ)$/i.test(ticker);
  return isKr ? 15 * 60 + 30 + 30 : 16 * 60 + 30;
}

/** YYYY-MM-DD in the market's local timezone. */
function localDateIso(now: Date, tz: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Minutes since midnight in the market's local timezone. */
function localMinutesOfDay(now: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  }).formatToParts(now);
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  // `hour: numeric` + hour12:false renders midnight as "24" in some
  // locales — normalize.
  return ((hour % 24) * 60) + minute;
}

/** Day-of-week in the market's local timezone. 0=Sun..6=Sat. */
function localDayOfWeek(now: Date, tz: string): number {
  const wd = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "short",
  }).format(now);
  // Sun..Sat
  return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(wd);
}

/**
 * Classify a bar's `asOf` (YYYY-MM-DD) relative to the current market
 * session. `now` is injectable for tests.
 *
 *   asOf == today (market local) AND minutes-of-day < cutoff   → "intraday"
 *   asOf == today AND past cutoff                              → "closed"
 *   asOf < today (or any non-today)                            → "stale"
 *
 * Weekends/holidays return "stale" because the latest bar can only be
 * from a prior trading day.
 */
export function classifySession(
  ticker: string,
  asOf: string,
  now: Date = new Date(),
): MarketSession {
  const tz = marketTimezone(ticker);
  const today = localDateIso(now, tz);
  if (asOf !== today) return "stale";
  const dow = localDayOfWeek(now, tz);
  if (dow === 0 || dow === 6) return "stale";   // weekend — shouldn't happen, but defensive
  const minutes = localMinutesOfDay(now, tz);
  return minutes >= cutoffMinutes(ticker) ? "closed" : "intraday";
}

/**
 * Human label for the LastClose card header — the EXACT bug we keep
 * re-introducing. Returns Korean text suitable for a chip-line title.
 *
 *   intraday  → "장중 가격 (마감 후 확정)"
 *   closed    → "최종 종가"
 *   stale     → "최종 종가 — 직전 거래일"
 */
export function priceLabelFor(
  ticker: string,
  asOf: string,
  now: Date = new Date(),
): string {
  const session = classifySession(ticker, asOf, now);
  if (session === "intraday") return "장중 가격 (마감 후 확정)";
  if (session === "closed") return "최종 종가";
  return "최종 종가 — 직전 거래일";
}
