/**
 * GET /api/quotes/realtime — near-real-time prices for a fixed set of
 * macro/market indices.
 *
 * Source: Yahoo Finance v8 chart endpoint (used internally by yfinance).
 * Yahoo's v7 `quote` bulk endpoint went Unauthorized in 2024, so we fan
 * out one parallel request per symbol — still fast (8 symbols ≈ 300ms).
 *
 * Cached at the edge for 60 seconds; the dashboard widget also polls
 * every minute, so each symbol hits Yahoo at most ~1×/min per region.
 */
import { NextResponse } from "next/server";

export const revalidate = 60;

type Quote = {
  symbol: string;
  label: string;
  price: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  currency: string | null;
  as_of: number | null;     // unix seconds
};

// Display order = render order. Korean label first because most users
// will look for KOSPI / KOSDAQ first.
const SYMBOLS: { symbol: string; label: string }[] = [
  { symbol: "^KS11",   label: "KOSPI" },
  { symbol: "^KQ11",   label: "KOSDAQ" },
  { symbol: "^GSPC",   label: "S&P 500" },
  { symbol: "^IXIC",   label: "NASDAQ" },
  { symbol: "^DJI",    label: "다우" },
  { symbol: "^VIX",    label: "VIX" },
  { symbol: "KRW=X",   label: "USD/KRW" },
  { symbol: "^TNX",    label: "美10Y" },
  { symbol: "CL=F",    label: "WTI" },
  { symbol: "GC=F",    label: "Gold" },
  { symbol: "BTC-USD", label: "BTC" },
];

const CHART_URL =
  "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d";

async function fetchOne(label: string, symbol: string): Promise<Quote> {
  const url = CHART_URL.replace("{symbol}", encodeURIComponent(symbol));
  const empty: Quote = {
    symbol, label, price: null, prev_close: null,
    change: null, change_pct: null, currency: null, as_of: null,
  };
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Accept: "application/json,*/*;q=0.1",
      },
      next: { revalidate },
    });
    if (!res.ok) return empty;
    const json = await res.json();
    const r = json?.chart?.result?.[0];
    if (!r) return empty;
    const meta = r.meta ?? {};
    const price: number | null =
      typeof meta.regularMarketPrice === "number" ? meta.regularMarketPrice : null;
    const prev: number | null =
      typeof meta.chartPreviousClose === "number" ? meta.chartPreviousClose : null;
    const change =
      price != null && prev != null ? price - prev : null;
    const changePct =
      change != null && prev ? (change / prev) * 100 : null;
    return {
      symbol, label,
      price,
      prev_close: prev,
      change,
      change_pct: changePct,
      currency: typeof meta.currency === "string" ? meta.currency : null,
      as_of: typeof meta.regularMarketTime === "number" ? meta.regularMarketTime : null,
    };
  } catch {
    return empty;
  }
}

export async function GET() {
  const quotes = await Promise.all(
    SYMBOLS.map(({ symbol, label }) => fetchOne(label, symbol)),
  );
  return NextResponse.json({ items: quotes });
}
