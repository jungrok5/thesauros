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
  //
  // Escape ilike wildcards in user input — `%` and `_` are SQL wildcards
  // and PostgREST also treats `,`/`.`/`*` as filter syntax. Without
  // escaping a query like "abc_d" would silently match "abcXd" too, and
  // a comma in the input could split the OR filter list.
  const escIlike = (s: string) =>
    s.replace(/[\\%_]/g, (m) => "\\" + m);
  const escFilter = (s: string) =>
    escIlike(s).replace(/[,()]/g, (m) => `\\${m}`);
  const safeQ = escFilter(q);
  const safeUpperQ = escFilter(q.toUpperCase());

  // Build OR filter manually
  const orFilters = [
    `ticker.ilike.${safeUpperQ}%`,        // 005930 → 005930.KS, 005930.KQ
    `ticker.ilike.${safeUpperQ}.%`,       // exact
    `name.ilike.%${safeQ}%`,
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
  // Use the unescaped original here — `safeUpperQ` has SQL escapes we
  // don't want when doing literal string compares.
  const upperQ = q.toUpperCase();
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

  // Always merge in Naver hits — local DB only knows our seeded
  // universe + each tickers row's canonical corporate name, so a query
  // like "마이크론" matches the KR ticker 마이크로닉스 locally but
  // never reaches the US Micron (MU) row whose name is "Micron
  // Technology". Without a merge, the KR-side match alone would
  // suppress the Naver lookup and the user sees only one side.
  const naverHits = await searchNaverStocks(q, limit);
  const seen = new Set(items.map((r) => String(r.ticker).toUpperCase()));
  const merged: unknown[] = [...items];
  for (const h of naverHits) {
    const t = h.ticker.toUpperCase();
    if (seen.has(t)) continue;
    seen.add(t);
    merged.push({
      ticker: h.ticker,
      name: h.name,
      market: h.market,
      sector: null,
      // Not in our master yet — /api/watchlist auto-seeds on first POST.
      external: true,
    });
    if (merged.length >= limit) break;
  }

  return NextResponse.json({ items: merged });
}
