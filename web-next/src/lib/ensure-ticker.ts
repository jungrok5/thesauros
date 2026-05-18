/**
 * `ensureTickerInMaster` — make sure a ticker exists in the Supabase
 * `tickers` master row, INSERT-ing it on the fly when missing. Needed
 * because `watchlist.ticker` has an FK to tickers; without this any
 * attempt to watchlist a US ticker that wasn't pre-seeded (or any
 * Korean-brand fallback like 샌디스크→SNDK that we resolve on demand)
 * would 500 with a FK violation.
 *
 * Verified flow:
 *   1. If already in tickers → return existing row.
 *   2. Else query Naver Finance integrated search for the ticker.
 *      - If Naver returns a matching `code`, we trust it: insert with
 *        the Korean display name + canonical market.
 *      - If Naver returns nothing, we REFUSE — return `existed: false,
 *        ticker: null` so the caller can 400 the user instead of
 *        polluting the master table with arbitrary strings like
 *        "FAKETICKERZZZ".
 *
 * Idempotent — `ON CONFLICT (ticker) DO NOTHING`. Safe to call from
 * any route that's about to persist a `ticker` value.
 */
import { getServerClient } from "@/lib/supabase";
import { searchNaverStocks } from "@/lib/naver-search";

export type EnsureResult =
  | {
      ok: true;
      existed: boolean;
      ticker: string;
      name: string | null;
      market: string | null;
    }
  | { ok: false; reason: "not_found" };

export async function ensureTickerInMaster(rawTicker: string): Promise<EnsureResult> {
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
      ok: true,
      existed: true,
      ticker: existing.ticker as string,
      name: (existing.name as string) ?? null,
      market: (existing.market as string) ?? null,
    };
  }

  // Verify against Naver — refuses to insert any string the upstream
  // doesn't know. This stops `watchlist` callers from polluting the
  // master with arbitrary brand-name strings the user might type.
  let name: string | null = null;
  let market: string | null = null;
  try {
    const hits = await searchNaverStocks(ticker, 5);
    const match = hits.find((h) => h.ticker.toUpperCase() === ticker);
    if (!match) return { ok: false, reason: "not_found" };
    name = match.name || null;
    market = match.market || null;
  } catch {
    // Naver outage shouldn't leave the user with a half-broken
    // watchlist; refuse rather than seed a placeholder.
    return { ok: false, reason: "not_found" };
  }

  await sb
    .from("tickers")
    .upsert(
      { ticker, name: name ?? ticker, market: market ?? "UNKNOWN", is_active: true },
      { onConflict: "ticker", ignoreDuplicates: true },
    );

  return { ok: true, existed: false, ticker, name, market };
}
