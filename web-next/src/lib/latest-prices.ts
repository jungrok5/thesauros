/**
 * Bulk-fetch latest weekly close + 1-week change for a list of tickers.
 *
 * Used by list pages (/screener) to show "5,300원 +7.2%"
 * next to each row without paying a per-row roundtrip. Two W bars per
 * ticker is plenty for "this week vs last week" — pull the most recent
 * 2 rows, sort by bar_date in JS.
 *
 * PostgREST hard-caps responses at 1000 rows. Two bars × 500 tickers =
 * 1000 → already at the ceiling. The list pages cap their tickers at
 * 500 (screener.runPreset `p_limit: 50` and themes.fetchThemeMembers
 * caps at 500), so we're safe — but assert it loudly if the cap is hit.
 */
import { getServerClient } from "@/lib/supabase";

export type LatestPrice = {
  /** Most recent weekly close. */
  close: number;
  /** Previous weekly close (one bar earlier). null if only one bar. */
  prevClose: number | null;
  /** (close - prevClose) / prevClose, as a fraction. null if unknown. */
  changePct: number | null;
  /** YYYY-MM-DD of the latest weekly bar. */
  barDate: string;
  /** Trailing weekly closes, oldest → newest. Up to SPARKLINE_BARS rows
   *  (currently 13 weeks). Used by <RowSparkline /> for the inline chart;
   *  same fetch as `close`/`changePct` so no extra round-trip. */
  series: number[];
};

/** How many weeks of close to pull for the sparkline. 13 = ~3 months —
 *  long enough to read direction, short enough that 50 tickers × 13 =
 *  650 rows stays under PostgREST's 1000-row cap. */
export const SPARKLINE_BARS = 13;

export interface FetchLatestPricesOptions {
  /** 2026-05-28 — callers that don't render a sparkline (e.g. the
   *  watchlist row strip which only needs close + return %) can opt
   *  into a 2-bar fetch (latest + prev). With 50 tickers this cuts
   *  the payload from 650 → 100 rows + leaves more headroom under
   *  the PostgREST 1000-row cap. */
  withSparkline?: boolean;
}

export async function fetchLatestPrices(
  tickers: string[],
  opts: FetchLatestPricesOptions = {},
): Promise<Map<string, LatestPrice>> {
  const out = new Map<string, LatestPrice>();
  if (tickers.length === 0) return out;

  const sb = getServerClient();
  const bars = opts.withSparkline === false ? 2 : SPARKLINE_BARS;
  // Fetch the most recent `bars` rows per ticker. PostgREST's flat
  // .order() + .limit() can't do "top-N per group", so we over-fetch
  // up to the 1000-row cap and group in JS.
  const limit = Math.min(1000, tickers.length * bars);
  const { data, error } = await sb
    .from("bars")
    .select("ticker, bar_date, close")
    .eq("granularity", "W")
    .in("ticker", tickers)
    .order("bar_date", { ascending: false })
    .limit(limit);
  if (error || !data) {
    console.error("latest-prices bars read:", error?.message);
    return out;
  }

  type Row = { ticker: string; bar_date: string; close: number | string };
  const grouped = new Map<string, Row[]>();
  for (const r of data as unknown as Row[]) {
    const arr = grouped.get(r.ticker) ?? [];
    if (arr.length < bars) {
      arr.push(r);
      grouped.set(r.ticker, arr);
    }
  }
  for (const [ticker, rows] of grouped) {
    if (rows.length === 0) continue;
    const latest = rows[0];
    const prev = rows[1] ?? null;
    const close = Number(latest.close);
    const prevClose = prev ? Number(prev.close) : null;
    const changePct =
      prevClose != null && prevClose > 0
        ? close / prevClose - 1
        : null;
    // Series oldest → newest (reverse of the DESC fetch). SPARKLINE uses
    // chronological order to draw left-to-right.
    const series = rows
      .map((r) => Number(r.close))
      .filter((n) => Number.isFinite(n) && n > 0)
      .reverse();
    out.set(ticker, {
      close,
      prevClose,
      changePct,
      barDate: latest.bar_date,
      series,
    });
  }
  return out;
}

/** Whether the ticker looks like a Korean code (NNNNNN.KS / .KQ). */
function isKrTicker(ticker: string): boolean {
  return /^[0-9]{6}\.(KS|KQ)$/.test(ticker);
}

/** Format a price for list-row display. KR rounds + adds "원"; US uses
 *  2-decimal USD. Caller decides which based on the ticker. */
export function formatRowPrice(value: number, ticker: string): string {
  if (isKrTicker(ticker)) {
    return `${Math.round(value).toLocaleString("ko-KR")}원`;
  }
  return `$${value.toFixed(2)}`;
}
