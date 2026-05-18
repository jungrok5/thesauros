/**
 * GET /api/news/[ticker] — real-time per-stock news from Naver Finance.
 *
 * Scrapes the curated 종목 뉴스 tab (`finance.naver.com/item/news_news.naver`)
 * which is what users see as "관련 뉴스" on Naver Finance. EUC-KR encoded
 * HTML; parsed with a stable-structure regex (no Node HTML parser needed).
 *
 * Cached at the edge for 5 minutes (`revalidate = 300`) so popular stocks
 * hit Naver at most once per 5-minute window per region, not per pageview.
 *
 * KR tickers only (NASDAQ/NYSE return an empty list). DART disclosures
 * are NOT here — those stay in Supabase `disclosures`.
 */
import { NextRequest, NextResponse } from "next/server";

// 5-minute ISR cache, keyed by URL. Honored by Vercel + local dev.
export const revalidate = 300;

const NAVER_URL =
  "https://finance.naver.com/item/news_news.naver" +
  "?code={code}&page=1&sm=title_entity_id.basic&clusterId=";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;

type NewsItem = {
  title: string;
  url: string;
  source: string | null;
  published_at: string | null;
};

function krCode(ticker: string): string | null {
  // 005380.KS / 005380.KQ → "005380". Foreign tickers → null.
  const m = ticker.toUpperCase().match(/^(\d{6})\.(KS|KQ)$/);
  return m ? m[1] : null;
}

/**
 * Extract `<tr>` items from `<table class="type5">`. Each article row
 * looks like:
 *   <tr>
 *     <td class="title"><a href="...">제목</a></td>
 *     <td class="info">출처</td>
 *     <td class="date">YYYY.MM.DD HH:MM</td>
 *   </tr>
 * Header / 더보기 / spacer rows are skipped (no `td.title a`).
 */
function parseNaverNews(html: string): NewsItem[] {
  // Narrow to the table first so we don't pick up unrelated <tr>s.
  const tableMatch = html.match(
    /<table[^>]*class="[^"]*type5[^"]*"[\s\S]*?<\/table>/i,
  );
  if (!tableMatch) return [];
  const tableHtml = tableMatch[0];

  const out: NewsItem[] = [];
  const trRe = /<tr[\s\S]*?<\/tr>/gi;
  for (const trMatch of tableHtml.matchAll(trRe)) {
    const tr = trMatch[0];
    const titleA = tr.match(
      /<td[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a\s+[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i,
    );
    if (!titleA) continue;
    const href = titleA[1];
    const title = stripTags(titleA[2]).trim();
    if (!title) continue;

    const articleUrl = href.startsWith("/")
      ? `https://finance.naver.com${href}`
      : href;

    const info = tr.match(/<td[^>]*class="[^"]*info[^"]*"[^>]*>([\s\S]*?)<\/td>/i);
    const date = tr.match(/<td[^>]*class="[^"]*date[^"]*"[^>]*>([\s\S]*?)<\/td>/i);

    const source = info ? stripTags(info[1]).trim() || null : null;
    let publishedIso: string | null = null;
    if (date) {
      const dtText = stripTags(date[1]).trim();
      publishedIso = parseNaverDate(dtText);
    }

    out.push({ title, url: articleUrl, source, published_at: publishedIso });
  }
  return out;
}

// HTML entities that appear in Naver Finance titles. Browsers do NOT
// auto-decode entities inside JSX text expressions, so we must do it here
// or users see literal "&ldquo;".
const ENTITY_MAP: Record<string, string> = {
  "&nbsp;": " ",
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&ldquo;": "“",
  "&rdquo;": "”",
  "&lsquo;": "‘",
  "&rsquo;": "’",
  "&hellip;": "…",
  "&middot;": "·",
  "&ndash;": "–",
  "&mdash;": "—",
};

function stripTags(s: string): string {
  let out = s.replace(/<[^>]+>/g, "");
  out = out.replace(/&[a-z#0-9]+;/gi, (m) => {
    if (ENTITY_MAP[m]) return ENTITY_MAP[m];
    // numeric refs: &#1234; or &#x1A2B;
    const numMatch = m.match(/^&#(x?)([0-9a-f]+);$/i);
    if (numMatch) {
      const cp = parseInt(numMatch[2], numMatch[1] ? 16 : 10);
      if (Number.isFinite(cp) && cp > 0) return String.fromCodePoint(cp);
    }
    return m;
  });
  return out;
}

/** "2026.05.18 14:32" or "2026.05.18" → ISO with +09:00. */
function parseNaverDate(s: string): string | null {
  const m =
    s.match(/^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$/) ??
    s.match(/^(\d{4})\.(\d{2})\.(\d{2})$/);
  if (!m) return null;
  const [, y, mo, d, hh = "00", mm = "00"] = m;
  // KST = UTC+9; construct an ISO string with offset directly to avoid
  // any host-timezone interpretation.
  return `${y}-${mo}-${d}T${hh}:${mm}:00+09:00`;
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw).toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }

  const code = krCode(ticker);
  if (!code) {
    // Non-KR ticker → no news source wired (Naver covers KR only).
    // `supported: false` lets the UI render a dedicated message instead
    // of an ambiguous "no news found".
    return NextResponse.json({
      items: [],
      ticker,
      supported: false,
      note: "KR only",
    });
  }

  const url = NAVER_URL.replace("{code}", code);
  let html: string;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Referer: "https://finance.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9",
      },
      // Next.js will cache the upstream response for `revalidate` seconds.
      next: { revalidate },
    });
    if (!res.ok) {
      return NextResponse.json({ items: [], error: `upstream ${res.status}` });
    }
    // Naver Finance serves EUC-KR; decode explicitly.
    const buf = await res.arrayBuffer();
    html = new TextDecoder("euc-kr").decode(buf);
  } catch (e) {
    console.error("naver news fetch:", e);
    return NextResponse.json({ items: [], error: "fetch failed" });
  }

  const items = parseNaverNews(html).slice(0, 30);
  return NextResponse.json({
    items, ticker, supported: true, source: "naver_finance",
  });
}
