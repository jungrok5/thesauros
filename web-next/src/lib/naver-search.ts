/**
 * Naver Finance integrated stock search — fallback for queries that
 * miss our local `tickers` table.
 *
 * Why this exists: the local search only does ilike on (ticker, name).
 * Korean brand names ("샌디스크", "애플") and English consumer brands
 * ("GOOGLE") don't appear inside the canonical corporate names we
 * store ("Sandisk Corporation", "Apple Inc.", "Alphabet Inc..."), so
 * the local search returns zero results for them.
 *
 * Naver's `m.stock.naver.com/front-api/search` covers both KR and US
 * universes with Korean + English aliases, including consumer brand
 * matches. Used as a fallback only — local DB is tried first.
 */

export type NaverHit = {
  ticker: string;       // canonicalized to our schema (e.g. "005930.KS", "AAPL")
  name: string;         // Korean name when available
  market: string;       // "KOSPI" | "KOSDAQ" | "NASDAQ" | "NYSE" | "AMEX" | ...
  nation: "KR" | "US" | "OTHER";
};

interface NaverItem {
  code?: string;
  name?: string;
  typeCode?: string;        // "NASDAQ" / "KOSPI" / "KOSDAQ" / "AMEX" / ...
  typeName?: string;
  nationCode?: string;      // "KOR" / "USA" / "JPN" / ...
  category?: string;        // "stock" / "etf" / "index" / ...
}

const NAVER_URL =
  "https://m.stock.naver.com/front-api/search?q={q}&target=ALL&size={n}&page=1";

function toCanonicalTicker(item: NaverItem): string | null {
  const code = (item.code ?? "").toUpperCase();
  const type = (item.typeCode ?? "").toUpperCase();
  if (!code) return null;
  if (type === "KOSPI") return `${code}.KS`;
  if (type === "KOSDAQ") return `${code}.KQ`;
  // US / global: keep code as-is
  if (["NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"].includes(type)) return code;
  return code;
}

function nationOf(item: NaverItem): "KR" | "US" | "OTHER" {
  const n = (item.nationCode ?? "").toUpperCase();
  if (n === "KOR") return "KR";
  if (n === "USA") return "US";
  return "OTHER";
}

/**
 * Returns up to `limit` stock hits matching `q`. Filters out ETFs,
 * indexes, and non-KR/US listings to keep the result space focused on
 * tradeable single-stock matches.
 */
export async function searchNaverStocks(
  q: string,
  limit = 5,
): Promise<NaverHit[]> {
  const trimmed = q.trim();
  if (trimmed.length === 0) return [];
  // Naver returns 400 on very-short queries; cap the lower bound at 2.
  if (trimmed.length < 2) return [];

  const url = NAVER_URL
    .replace("{q}", encodeURIComponent(trimmed))
    .replace("{n}", String(Math.max(5, limit * 3)));

  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        Referer: "https://m.stock.naver.com/",
      },
      // Cache for 1h — search hits don't change minute-to-minute.
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    const json = await res.json();
    const items: NaverItem[] = json?.result?.items ?? [];
    const seen = new Set<string>();
    const out: NaverHit[] = [];
    for (const it of items) {
      if (it.category !== "stock") continue;
      const nation = nationOf(it);
      if (nation === "OTHER") continue;     // skip Japan, China, etc.
      const ticker = toCanonicalTicker(it);
      if (!ticker || seen.has(ticker)) continue;
      seen.add(ticker);
      out.push({
        ticker,
        name: (it.name ?? "").trim(),
        market: it.typeCode ?? "",
        nation,
      });
      if (out.length >= limit) break;
    }
    return out;
  } catch {
    return [];
  }
}
