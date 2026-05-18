/**
 * GET /api/search?q=...   — ticker / company-name fuzzy search.
 *
 * Uses pg_trgm GIN index on tickers.name (migrations/003). Returns
 * up to 20 best matches by `similarity` of name + an exact-ticker
 * shortcut at the top.
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerClient } from "@/lib/supabase";
import { searchNaverStocks } from "@/lib/naver-search";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") ?? "").trim();
  if (q.length < 1) {
    return NextResponse.json({ items: [] });
  }
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 20), 50);
  const sb = getServerClient();

  // Strategy:
  // 1) Try exact ticker match (case-insensitive, optional .KS/.KQ suffix).
  // 2) Then fuzzy ilike on ticker prefix.
  // 3) Then fuzzy ilike on name.
  // (We use ilike because PostgREST doesn't expose pg_trgm operators
  //  directly; the underlying gin_trgm_ops index still accelerates ilike.)
  const upperQ = q.toUpperCase();

  // Build OR filter manually
  const orFilters = [
    `ticker.ilike.${upperQ}%`,         // 005930 → 005930.KS, 005930.KQ
    `ticker.ilike.${upperQ}.%`,        // exact
    `name.ilike.%${q}%`,
  ].join(",");

  const { data, error } = await sb
    .from("tickers")
    .select("ticker, name, market, sector")
    .eq("is_active", true)
    .or(orFilters)
    .limit(limit);

  if (error) {
    console.error("search error:", error.message);
    return NextResponse.json({ items: [], error: "search failed" }, { status: 500 });
  }

  // Rank: exact ticker match first, then prefix match, then name match.
  const items = (data ?? [])
    .map((row) => {
      const t = String(row.ticker).toUpperCase();
      let score = 0;
      if (t === upperQ || t.split(".")[0] === upperQ) score = 100;
      else if (t.startsWith(upperQ)) score = 80;
      else if (String(row.name).toLowerCase().startsWith(q.toLowerCase())) score = 60;
      else if (String(row.name).toLowerCase().includes(q.toLowerCase())) score = 40;
      else score = 10;
      return { ...row, _score: score };
    })
    .sort((a, b) => b._score - a._score)
    .slice(0, limit)
    .map(({ _score, ...row }) => {
      void _score;
      return row;
    });

  // Fallback: if the local search returned nothing, ask Naver — covers
  // Korean brand names ("샌디스크") and English consumer brands
  // ("GOOGLE") that don't appear inside our canonical corporate names.
  if (items.length === 0) {
    const naverHits = await searchNaverStocks(q, limit);
    if (naverHits.length > 0) {
      return NextResponse.json({
        items: naverHits.map((h) => ({
          ticker: h.ticker,
          name: h.name,
          market: h.market,
          sector: null,
          // Hint to the client that this row isn't in our master yet —
          // /api/watchlist will auto-seed it on first POST.
          external: true,
        })),
        source: "naver",
      });
    }
  }

  return NextResponse.json({ items });
}
