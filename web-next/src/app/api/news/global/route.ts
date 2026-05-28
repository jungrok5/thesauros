/**
 * GET /api/news/global — merged global + KR market breaking news.
 *
 * Sources:
 *   - Investing.com 한국어 RSS — global market breaking (Fed / 유가 /
 *     미국 증시 / 지정학 / 환율). Updates roughly every few minutes.
 *   - 연합뉴스 경제 RSS — KR economy + market. Wire-service tempo.
 *
 * Merged, deduped by URL, sorted by publication time desc. Cached at
 * the edge for 5 minutes so this rss-fetcher hits each upstream at
 * most once per 5-min window per region.
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { rateLimit } from "@/lib/rate-limit";

export const revalidate = 300;

type Item = {
  title: string;
  url: string;
  source: string;
  published_at: string;   // ISO
};

const FEEDS: { source: string; url: string }[] = [
  { source: "Investing.com", url: "https://kr.investing.com/rss/news.rss" },
  { source: "연합뉴스",       url: "https://www.yna.co.kr/rss/economy.xml" },
];


function decodeEntities(s: string): string {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&ldquo;/g, "“")
    .replace(/&rdquo;/g, "”")
    .replace(/&hellip;/g, "…")
    .replace(/&middot;/g, "·")
    .replace(/&#(x?)([0-9a-f]+);/gi, (_m, hex: string, code: string) => {
      const cp = parseInt(code, hex ? 16 : 10);
      return Number.isFinite(cp) && cp > 0 ? String.fromCodePoint(cp) : "";
    });
}

function parseTag(xml: string, tag: string): string | null {
  // Greedy across whitespace, non-greedy on content. Handles CDATA.
  const m = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  return m ? decodeEntities(m[1]).trim() : null;
}

/**
 * Parse the `<pubDate>` value into an ISO string. Handles:
 *   - RFC 2822: "Mon, 18 May 2026 09:28:55 +0900"  (연합뉴스)
 *   - Plain:    "2026-05-18 00:32:17"               (Investing.com — KST implied)
 */
function parseDate(raw: string | null): string | null {
  if (!raw) return null;
  // RFC 2822 / standard — let Date parse it.
  const d1 = new Date(raw);
  if (!isNaN(d1.getTime())) return d1.toISOString();
  // "YYYY-MM-DD HH:MM:SS" → assume KST.
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/);
  if (m) {
    const [, y, mo, d, hh, mm, ss] = m;
    return `${y}-${mo}-${d}T${hh}:${mm}:${ss}+09:00`;
  }
  return null;
}

async function fetchFeed(source: string, url: string): Promise<Item[]> {
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Accept: "application/rss+xml,application/xml,text/xml,*/*;q=0.1",
      },
      next: { revalidate },
    });
    if (!res.ok) return [];
    const xml = await res.text();
    const out: Item[] = [];
    // Split into <item>...</item> blocks. Drop the feed-level <title>.
    const itemRe = /<item[^>]*>([\s\S]*?)<\/item>/gi;
    for (const m of xml.matchAll(itemRe)) {
      const block = m[1];
      const title = parseTag(block, "title");
      const link = parseTag(block, "link");
      const pub = parseTag(block, "pubDate");
      if (!title || !link) continue;
      const iso = parseDate(pub);
      out.push({
        title,
        url: link,
        source,
        published_at: iso ?? new Date().toISOString(),
      });
    }
    return out;
  } catch (e) {
    console.error("rss fetch", source, e);
    return [];
  }
}


export async function GET() {
  // 2026-05-28 — auth + rate limit (same rationale as /api/news/[ticker]).
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (rateLimit(`news-global:${session.user.email}`, { limit: 20, windowMs: 60_000 })) {
    return NextResponse.json({ error: "rate_limited" }, { status: 429 });
  }
  const results = await Promise.all(
    FEEDS.map((f) => fetchFeed(f.source, f.url)),
  );
  const merged = results.flat();

  // Dedupe by URL, keeping the first occurrence.
  const seen = new Set<string>();
  const dedup: Item[] = [];
  for (const it of merged) {
    if (seen.has(it.url)) continue;
    seen.add(it.url);
    dedup.push(it);
  }

  // Sort by published_at desc and cap.
  dedup.sort((a, b) => b.published_at.localeCompare(a.published_at));
  return NextResponse.json({ items: dedup.slice(0, 30) });
}
