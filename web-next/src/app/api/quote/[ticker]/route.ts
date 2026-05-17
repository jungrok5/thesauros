/**
 * GET /api/quote/[ticker] — last-close quote from Supabase bars_daily.
 *
 * Previously proxied to FastAPI which called KIS for KR live prices.
 * Now we just return the latest two bars from bars_daily and compute
 * change/change_pct. Not real-time — but the site is book-faithful and
 * the book is a 종가매매 (close-price trading) framework.
 *
 * Live KIS prices can be re-introduced as a separate Node-side
 * integration if/when needed; doing it here without backend would need
 * KIS token caching in Supabase.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;

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

  const sb = getServerClient();
  const { data, error } = await sb
    .from("bars_daily")
    .select("bar_date, open, high, low, close, volume")
    .eq("ticker", ticker)
    .order("bar_date", { ascending: false })
    .limit(2);

  if (error) {
    console.error("bars_daily read:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  if (!data || data.length === 0) {
    return NextResponse.json(
      { error: "no price data", ticker },
      { status: 404 },
    );
  }

  const latest = data[0];
  const prev = data[1];
  const close = num(latest.close);
  const prevClose = prev ? num(prev.close) : null;
  const change =
    close != null && prevClose != null ? close - prevClose : null;
  const changePct =
    change != null && prevClose ? (change / prevClose) * 100 : null;

  return NextResponse.json({
    ticker,
    as_of: latest.bar_date,
    price: close,
    change,
    change_pct: changePct,
    open: num(latest.open),
    high: num(latest.high),
    low: num(latest.low),
    volume: int(latest.volume),
    source: "bars_daily (last close)",
  });
}

function num(v: unknown): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function int(v: unknown): number | null {
  const n = num(v);
  return n == null ? null : Math.trunc(n);
}
