/**
 * `ensureTickerInMaster` — make sure a ticker exists in the Supabase
 * `tickers` master row, INSERT-ing it on the fly when missing. Needed
 * because `watchlist.ticker` has an FK to tickers; without this any
 * attempt to watchlist a US ticker that wasn't pre-seeded (or any
 * Korean-brand fallback like 샌디스크→SNDK that we resolve on demand)
 * would 500 with a FK violation.
 *
 * Idempotent — `ON CONFLICT (ticker) DO NOTHING`. Safe to call from
 * any route that's about to persist a `ticker` value.
 */
import { getServerClient } from "@/lib/supabase";
import { searchNaverStocks } from "@/lib/naver-search";

/**
 * Returns `{ existed, ticker }`. `ticker` is always the canonical form
 * (caller's input upper-cased). When the row didn't exist we try a
 * Naver search to pull the Korean name + market, otherwise fall back
 * to a minimal record so the FK is at least satisfied.
 */
export async function ensureTickerInMaster(rawTicker: string): Promise<{
  existed: boolean;
  ticker: string;
  name: string | null;
  market: string | null;
}> {
  const ticker = rawTicker.trim().toUpperCase();
  const sb = getServerClient();

  // Fast path: already there.
  const { data: existing } = await sb
    .from("tickers")
    .select("ticker, name, market")
    .eq("ticker", ticker)
    .maybeSingle();
  if (existing) {
    return {
      existed: true,
      ticker: existing.ticker as string,
      name: (existing.name as string) ?? null,
      market: (existing.market as string) ?? null,
    };
  }

  // Try Naver to learn a friendlier name + correct market for the
  // ticker. Best-effort — if Naver is down we still insert the bare row.
  let name: string | null = null;
  let market: string | null = null;
  try {
    const hits = await searchNaverStocks(ticker, 5);
    const match = hits.find((h) => h.ticker.toUpperCase() === ticker);
    if (match) {
      name = match.name || null;
      market = match.market || null;
    }
  } catch {
    /* swallow — proceed with minimal row */
  }

  // Infer market from suffix when Naver gave nothing.
  if (!market) {
    if (ticker.endsWith(".KS")) market = "KOSPI";
    else if (ticker.endsWith(".KQ")) market = "KOSDAQ";
    else market = "UNKNOWN";
  }
  // Insert. ON CONFLICT DO NOTHING in case a concurrent request raced us.
  await sb
    .from("tickers")
    .upsert(
      { ticker, name: name ?? ticker, market, is_active: true },
      { onConflict: "ticker", ignoreDuplicates: true },
    );

  return { existed: false, ticker, name, market };
}
