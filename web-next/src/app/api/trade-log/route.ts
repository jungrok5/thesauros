/**
 * GET    /api/trade-log              — list current user's trades (latest 50)
 * POST   /api/trade-log              — add {ticker, action, price, quantity?, trade_date, reason?}
 * DELETE /api/trade-log?id=N         — remove single row
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9]{1,12}(\.[A-Z]{1,4})?$/i;
const DATE_RE   = /^\d{4}-\d{2}-\d{2}$/;
const REASON_MAX = 300;

async function currentUser() {
  const session = await auth();
  if (!session?.user?.email) return null;
  return {
    email: session.user.email.toLowerCase(),
    name: session.user.name ?? null,
  };
}

export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("trade_log")
    .select("id, ticker, action, price, quantity, trade_date, reason, created_at")
    .eq("user_id", userId)
    .order("trade_date", { ascending: false })
    .limit(50);
  if (error) return NextResponse.json({ error: "db error" }, { status: 500 });
  return NextResponse.json({ items: data });
}

export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim().toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  const action = body.action === "sell" ? "sell" : body.action === "buy" ? "buy" : null;
  if (!action) {
    return NextResponse.json({ error: "action must be buy|sell" }, { status: 400 });
  }
  const price = Number(body.price);
  if (!Number.isFinite(price) || price <= 0) {
    return NextResponse.json({ error: "invalid price" }, { status: 400 });
  }
  const qty = body.quantity != null && Number.isFinite(Number(body.quantity))
    ? Math.max(0, Math.floor(Number(body.quantity))) : null;
  const tradeDate = body.trade_date && DATE_RE.test(String(body.trade_date))
    ? String(body.trade_date)
    : new Date().toISOString().slice(0, 10);
  const reason = body.reason ? String(body.reason).slice(0, REASON_MAX) : null;

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("trade_log")
    .insert({
      user_id: userId, ticker, action, price,
      quantity: qty, trade_date: tradeDate, reason,
    })
    .select()
    .single();
  if (error) {
    console.error("trade-log insert:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ item: data });
}

export async function DELETE(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const url = new URL(req.url);
  const id = Number(url.searchParams.get("id"));
  if (!Number.isInteger(id) || id <= 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { error } = await sb
    .from("trade_log")
    .delete()
    .eq("user_id", userId)
    .eq("id", id);
  if (error) return NextResponse.json({ error: "db error" }, { status: 500 });
  return NextResponse.json({ ok: true });
}
