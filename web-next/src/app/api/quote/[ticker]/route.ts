/**
 * /api/quote/[ticker] → proxy to FastAPI /api/quote/{ticker}.
 * KIS live current-price for KR tickers (KIS_ENV=vts).
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ ticker: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { ticker } = await ctx.params;
  const safe = decodeURIComponent(ticker).toUpperCase();
  if (!/^[A-Z0-9._-]{1,16}$/.test(safe)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!/\.(KS|KQ)$/.test(safe)) {
    return NextResponse.json({ error: "KIS quote supports KR only" }, { status: 400 });
  }
  try {
    const r = await fetch(`${BACKEND}/api/quote/${encodeURIComponent(safe)}`, {
      cache: "no-store",
    });
    const text = await r.text();
    return new NextResponse(text, {
      status: r.status,
      headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return NextResponse.json({ error: "backend unreachable", detail: String(e) }, { status: 502 });
  }
}
