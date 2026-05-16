/**
 * Proxy /api/chart → Python backend /api/book/chart.
 *
 * Keeps the FastAPI URL server-only (BACKEND_URL is not NEXT_PUBLIC_).
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = new URL(req.url);
  const ticker = url.searchParams.get("ticker") ?? "";
  const timeframe = url.searchParams.get("timeframe") ?? "weekly";
  const years = url.searchParams.get("years") ?? "2";
  if (!/^[A-Z0-9._-]{1,16}$/i.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!/^(daily|weekly|monthly)$/.test(timeframe)) {
    return NextResponse.json({ error: "invalid timeframe" }, { status: 400 });
  }
  if (!/^\d{1,2}$/.test(years)) {
    return NextResponse.json({ error: "invalid years" }, { status: 400 });
  }
  const target = `${BACKEND}/api/book/chart?ticker=${encodeURIComponent(ticker)}&timeframe=${timeframe}&years=${years}`;
  try {
    const r = await fetch(target, { cache: "no-store" });
    const text = await r.text();
    return new NextResponse(text, {
      status: r.status,
      headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return NextResponse.json({ error: "backend unreachable", detail: String(e) }, { status: 502 });
  }
}
