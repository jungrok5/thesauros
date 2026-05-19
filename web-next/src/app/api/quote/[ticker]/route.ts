/**
 * GET /api/quote/[ticker] — last-close quote.
 *
 * Reads the latest two WEEKLY bars from Supabase `bars` (granularity='W',
 * the post-pivot canonical source). Computes change / change_pct.
 *
 * Not real-time — the book is a 종가매매 (close-price trading) framework
 * and weekly bars are the operating cadence. Daily bars (`bars_daily`)
 * were dropped in the weekly pivot (migration 021), so any caller still
 * trying that table returns nothing — this route now points at the
 * source the cron actually writes.
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
    .from("bars")
    .select("bar_date, open, high, low, close, volume")
    .eq("ticker", ticker)
    .eq("granularity", "W")
    .order("bar_date", { ascending: false })
    .limit(2);

  if (error) {
    console.error("bars (W) read:", error.message);
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
    source: "bars (W, last close)",
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
