/**
 * GET /api/quote/[ticker] — last-close quote.
 *
 * Reads the latest daily close directly from an upstream source rather
 * than the Supabase `bars` table (which stores weekly aggregates with a
 * Friday week-ending bar_date — that's the right shape for the book's
 * weekly analysis, but mid-week it can't tell us the actual calendar
 * date of the most recent close). Going upstream gives us an
 * authoritative `(date, close, prev_close)` pair every time.
 *
 *   KR (\d{6}\.(KS|KQ)) → api.stock.naver.com day chart (count=2)
 *   US (everything else)  → query1.finance.yahoo.com v8 chart (range=5d)
 *
 * Both responses include the actual local trading date with each price
 * point, so `as_of` is whatever date the upstream attached. No clamping
 * needed.
 *
 * Cached 5 minutes at the edge so repeated views of the same ticker
 * don't hit the upstreams every render.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";
export const revalidate = 300;

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;
const KR_RE = /^(\d{6})\.(KS|KQ)$/;

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw).toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }

  const krMatch = ticker.match(KR_RE);
  const fetched = krMatch
    ? await fetchKR(krMatch[1])
    : await fetchUS(ticker);

  if (!fetched) {
    return NextResponse.json(
      { error: "no price data", ticker },
      { status: 404 },
    );
  }

  return NextResponse.json({
    ticker,
    as_of: fetched.asOf,
    price: fetched.close,
    change: fetched.change,
    change_pct: fetched.changePct,
    open: fetched.open,
    high: fetched.high,
    low: fetched.low,
    volume: fetched.volume,
    source: fetched.source,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Upstream fetchers
// ─────────────────────────────────────────────────────────────────────

type QuoteData = {
  asOf: string;        // YYYY-MM-DD
  close: number;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  change: number | null;
  changePct: number | null;
  source: string;
};

async function fetchKR(code: string): Promise<QuoteData | null> {
  // count=2 gives us today (or last completed day) + the prior trading
  // day so we can compute change. The endpoint returns NEWEST-first.
  const url = `https://api.stock.naver.com/chart/domestic/item/${code}/day?count=2`;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0",
        Referer: "https://m.stock.naver.com/",
      },
      next: { revalidate },
    });
    if (!res.ok) return null;
    const rows = (await res.json()) as Array<{
      localDate: string;       // "YYYYMMDD"
      closePrice: number;
      openPrice: number;
      highPrice: number;
      lowPrice: number;
      accumulatedTradingVolume: number;
    }>;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const latest = rows[0];
    const prev = rows[1];
    const asOf = `${latest.localDate.slice(0, 4)}-${latest.localDate.slice(4, 6)}-${latest.localDate.slice(6, 8)}`;
    const change = prev ? latest.closePrice - prev.closePrice : null;
    const changePct =
      change != null && prev?.closePrice
        ? (change / prev.closePrice) * 100
        : null;
    return {
      asOf,
      close: latest.closePrice,
      open: latest.openPrice,
      high: latest.highPrice,
      low: latest.lowPrice,
      volume: latest.accumulatedTradingVolume,
      change,
      changePct,
      source: "naver_day_chart",
    };
  } catch (e) {
    console.error("[quote KR] naver fetch:", e);
    return null;
  }
}

async function fetchUS(ticker: string): Promise<QuoteData | null> {
  // 5d window so even Monday gets a `prev_close` from the prior Friday;
  // Yahoo's `chart` is daily by default.
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}` +
    `?range=5d&interval=1d&includePrePost=false`;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
          "AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        Accept: "application/json",
      },
      next: { revalidate },
    });
    if (!res.ok) return null;
    const payload = await res.json();
    const r = payload?.chart?.result?.[0];
    if (!r) return null;
    const tsList: number[] = r.timestamp ?? [];
    const quote = r.indicators?.quote?.[0] ?? {};
    const closes: (number | null)[] = quote.close ?? [];
    const opens: (number | null)[] = quote.open ?? [];
    const highs: (number | null)[] = quote.high ?? [];
    const lows: (number | null)[] = quote.low ?? [];
    const volumes: (number | null)[] = quote.volume ?? [];

    // Walk newest-first, find latest day with a non-null close.
    let i = tsList.length - 1;
    while (i >= 0 && closes[i] == null) i--;
    if (i < 0) return null;
    let prevI = i - 1;
    while (prevI >= 0 && closes[prevI] == null) prevI--;

    const asOf = new Date(tsList[i] * 1000).toISOString().slice(0, 10);
    const close = closes[i]!;
    const prevClose = prevI >= 0 ? closes[prevI] : null;
    const change = prevClose != null ? close - prevClose : null;
    const changePct =
      change != null && prevClose ? (change / prevClose) * 100 : null;

    return {
      asOf,
      close,
      open: opens[i] ?? null,
      high: highs[i] ?? null,
      low: lows[i] ?? null,
      volume: volumes[i] ?? null,
      change,
      changePct,
      source: "yahoo_v8_chart",
    };
  } catch (e) {
    console.error("[quote US] yahoo fetch:", e);
    return null;
  }
}
