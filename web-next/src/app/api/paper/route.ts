/**
 * /api/paper — list & create paper trades for the logged-in user.
 *
 *   GET     ?status=open|all   → paper trades w/ live P&L
 *   POST    body: {
 *     ticker, amount_krw, entry_price, stop_loss?, target?, notes?
 *   }
 *     Validates non-double-buy + amount > 0 + entry_price > 0,
 *     computes shares = amount_krw / entry_price, snapshots
 *     stop_loss/target straight from the request body (the page
 *     reads them from the analyzer's entry_plan).
 *
 * Close uses POST /api/paper/[id]/close with body { reason }.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import {
  fetchOpenTradesForUser, fetchAllTradesForUser,
  fetchOpenForUserTicker, computeStats,
} from "@/lib/paper-trades";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const status = req.nextUrl.searchParams.get("status") ?? "open";
  const rows = status === "all"
    ? await fetchAllTradesForUser(userId)
    : await fetchOpenTradesForUser(userId);
  return NextResponse.json({ rows, stats: computeStats(rows) });
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const body = await req.json().catch(() => ({}));

  const ticker = typeof body.ticker === "string"
    ? body.ticker.trim().toUpperCase()
    : "";
  const amount_krw = Number(body.amount_krw);
  const entry_price = Number(body.entry_price);
  const stop_loss = body.stop_loss != null ? Number(body.stop_loss) : null;
  const target = body.target != null ? Number(body.target) : null;
  const notes = typeof body.notes === "string"
    ? body.notes.slice(0, 500)
    : null;

  if (!ticker || !/^[0-9A-Z.]{3,15}$/.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!Number.isFinite(amount_krw) || amount_krw <= 0) {
    return NextResponse.json(
      { error: "amount_krw must be > 0" }, { status: 400 });
  }
  if (!Number.isFinite(entry_price) || entry_price <= 0) {
    return NextResponse.json(
      { error: "entry_price must be > 0" }, { status: 400 });
  }
  if (stop_loss != null && (!Number.isFinite(stop_loss) || stop_loss <= 0)) {
    return NextResponse.json({ error: "invalid stop_loss" }, { status: 400 });
  }
  if (target != null && (!Number.isFinite(target) || target <= 0)) {
    return NextResponse.json({ error: "invalid target" }, { status: 400 });
  }
  // Book sanity — stop < entry < target. Reject obviously-broken plans
  // before they hit the DB; the analyzer itself enforces this, but
  // someone hand-editing the modal could send garbage.
  if (stop_loss != null && stop_loss >= entry_price) {
    return NextResponse.json(
      { error: "stop_loss must be < entry_price" }, { status: 400 });
  }
  if (target != null && target <= entry_price) {
    return NextResponse.json(
      { error: "target must be > entry_price" }, { status: 400 });
  }

  // Block double-buy on the same open ticker so the user doesn't
  // accidentally stack positions. They can close the existing one
  // first if they want to re-enter.
  const existing = await fetchOpenForUserTicker(userId, ticker);
  if (existing.length > 0) {
    return NextResponse.json(
      { error: "이 종목은 이미 가짜 매수 중입니다 — /paper 에서 청산 후 재진입" },
      { status: 409 },
    );
  }

  const shares = amount_krw / entry_price;

  const sb = getServerClient();
  const { data, error } = await sb
    .from("paper_trades")
    .insert({
      user_id: userId,
      ticker,
      entry_price,
      amount_krw,
      shares,
      stop_loss,
      target,
      notes,
    })
    .select()
    .single();
  if (error || !data) {
    console.error("paper_trades insert:", error?.message);
    return NextResponse.json(
      { error: "insert failed" }, { status: 500 });
  }
  return NextResponse.json({ row: data });
}
