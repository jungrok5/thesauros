/**
 * GET /api/chart?ticker=...&timeframe=daily|weekly|monthly&years=N
 *
 * Reads precomputed chart payload from Supabase `chart_data` (populated
 * daily by app.db.scan_daily → app.db.publish_chart). No FastAPI hop.
 *
 * Response shape (unchanged from the old FastAPI proxy):
 *   { ticker, timeframe, bars, mas, patterns, quarter_lines, last_candle }
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;
const TIMEFRAME_RE = /^(daily|weekly|monthly)$/;

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = new URL(req.url);
  const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
  const timeframe = url.searchParams.get("timeframe") ?? "weekly";
  const yearsStr = url.searchParams.get("years") ?? "2";

  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!TIMEFRAME_RE.test(timeframe)) {
    return NextResponse.json({ error: "invalid timeframe" }, { status: 400 });
  }
  const years = Number(yearsStr);
  if (!Number.isInteger(years) || years < 1 || years > 20) {
    return NextResponse.json({ error: "invalid years" }, { status: 400 });
  }

  const sb = getServerClient();
  const { data, error } = await sb
    .from("chart_data")
    .select("payload, updated_at")
    .eq("ticker", ticker)
    .eq("timeframe", timeframe)
    .eq("years", years)
    .maybeSingle();

  if (error) {
    console.error("chart_data read:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  if (!data) {
    return NextResponse.json(
      {
        error: "no precomputed chart for this ticker/timeframe",
        hint: `run: python -m app.db.publish_chart --ticker ${ticker}`,
      },
      { status: 404 },
    );
  }
  return NextResponse.json(data.payload);
}
