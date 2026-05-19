/**
 * GET /api/news/[ticker] — real-time per-stock news.
 *
 *   - KR ticker (^\d{6}\.(KS|KQ)$): Naver Finance 종목뉴스 scrape
 *   - US ticker (everything else): Google News RSS search
 *
 * Both paths share the 5-minute edge cache (`revalidate = 300`) and the
 * same `{ items, ticker, supported, source }` response shape so the UI
 * doesn't branch.
 *
 * DART disclosures and SEC filings are NOT here — those go to Supabase
 * `disclosures` via a separate weekly cron.
 */
import { NextRequest, NextResponse } from "next/server";
import {
  parseGoogleNewsRss,
  parseNaverNews,
} from "@/lib/news-parsers";

export const revalidate = 300;

const NAVER_URL =
  "https://finance.naver.com/item/news_news.naver" +
  "?code={code}&page=1&sm=title_entity_id.basic&clusterId=";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;

function krCode(ticker: string): string | null {
  // 005380.KS / 005380.KQ → "005380". Foreign tickers → null.
  const m = ticker.toUpperCase().match(/^(\d{6})\.(KS|KQ)$/);
  return m ? m[1] : null;
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
  if (code) {
    return await fetchKrNews(ticker, code);
  }
  return await fetchUsNews(ticker);
}

async function fetchKrNews(
  ticker: string,
  code: string,
): Promise<NextResponse> {
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

/**
 * Google News RSS search for the ticker — works for any US/global symbol
 * Naver doesn't cover. Free, no rate limit at our scale, stable XML.
 * `$AAPL stock` biases the search toward equity coverage rather than
 * the company in general.
 */
async function fetchUsNews(ticker: string): Promise<NextResponse> {
  const q = encodeURIComponent(`$${ticker} stock`);
  const url =
    `https://news.google.com/rss/search?q=${q}` +
    `&hl=en-US&gl=US&ceid=US:en`;
  let xml: string;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Accept: "application/rss+xml, application/xml, text/xml",
      },
      next: { revalidate },
    });
    if (!res.ok) {
      return NextResponse.json({ items: [], error: `upstream ${res.status}` });
    }
    xml = await res.text();
  } catch (e) {
    console.error("google news fetch:", e);
    return NextResponse.json({ items: [], error: "fetch failed" });
  }
  const items = parseGoogleNewsRss(xml).slice(0, 30);
  return NextResponse.json({
    items, ticker, supported: true, source: "google_news_rss",
  });
}
