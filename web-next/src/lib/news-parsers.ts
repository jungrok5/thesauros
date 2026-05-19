/**
 * Pure-function parsers for /api/news/[ticker] upstream payloads.
 *
 * Extracted so they're unit-testable without network. The route handler
 * owns the fetch + caching wiring; this module owns the regex parsing
 * and entity decoding so a change to either side doesn't require
 * rewriting the test fixtures.
 */

export type NewsItem = {
  title: string;
  url: string;
  source: string | null;
  published_at: string | null;
};

// HTML entities that appear in Naver Finance titles. Browsers do NOT
// auto-decode entities inside JSX text expressions, so we must do it
// here or users see literal "&ldquo;".
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

export function stripTags(s: string): string {
  let out = s.replace(/<[^>]+>/g, "");
  out = out.replace(/&[a-z#0-9]+;/gi, (m) => {
    if (ENTITY_MAP[m]) return ENTITY_MAP[m];
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
export function parseNaverDate(s: string): string | null {
  const m =
    s.match(/^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$/) ??
    s.match(/^(\d{4})\.(\d{2})\.(\d{2})$/);
  if (!m) return null;
  const [, y, mo, d, hh = "00", mm = "00"] = m;
  return `${y}-${mo}-${d}T${hh}:${mm}:00+09:00`;
}

/**
 * Parse Naver Finance 종목뉴스 (`table.type5`). Skips header/spacer
 * rows by requiring `td.title a` in each row.
 */
export function parseNaverNews(html: string): NewsItem[] {
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
    const publishedIso = date
      ? parseNaverDate(stripTags(date[1]).trim())
      : null;

    out.push({ title, url: articleUrl, source, published_at: publishedIso });
  }
  return out;
}

/**
 * Google News RSS `<item>` structure (US-news path):
 *   <item>
 *     <title>Headline - Source</title>
 *     <link>https://news.google.com/rss/articles/...</link>
 *     <pubDate>Mon, 19 May 2026 14:32:00 GMT</pubDate>
 *     <source url="...">Source Name</source>
 *   </item>
 * Each title ends with " - <Source>" — we split it off so the UI can
 * render source separately like the Naver path does.
 */
export function parseGoogleNewsRss(xml: string): NewsItem[] {
  const out: NewsItem[] = [];
  const itemRe = /<item[^>]*>([\s\S]*?)<\/item>/gi;
  for (const m of xml.matchAll(itemRe)) {
    const block = m[1];
    const rawTitle = pick(block, "title");
    const link = pick(block, "link");
    const pub = pick(block, "pubDate");
    const sourceTag = block.match(/<source[^>]*>([\s\S]*?)<\/source>/i);
    if (!rawTitle || !link) continue;

    let title = stripTags(rawTitle).trim();
    let source: string | null = sourceTag ? stripTags(sourceTag[1]).trim() : null;
    const dashIdx = title.lastIndexOf(" - ");
    if (!source && dashIdx > 0) {
      source = title.slice(dashIdx + 3).trim();
      title = title.slice(0, dashIdx).trim();
    } else if (source && title.endsWith(` - ${source}`)) {
      title = title.slice(0, -(` - ${source}`.length)).trim();
    }

    const publishedIso = pub ? toIsoFromRfc822(stripTags(pub).trim()) : null;
    out.push({ title, url: link.trim(), source, published_at: publishedIso });
  }
  return out;
}

function pick(block: string, tag: string): string | null {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\/${tag}>`, "i");
  const m = block.match(re);
  return m ? m[1] : null;
}

function toIsoFromRfc822(s: string): string | null {
  const t = Date.parse(s);
  return Number.isFinite(t) ? new Date(t).toISOString() : null;
}
