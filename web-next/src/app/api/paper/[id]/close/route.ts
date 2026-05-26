/**
 * POST /api/paper/[id]/close
 *
 *  body: { reason?: string }
 *
 * Marks the trade closed at the latest weekly close. status routing:
 *   · current_price <= stop_loss → "closed_stop"
 *   · current_price >= target    → "closed_target"
 *   · else                       → "closed_manual"
 *
 * exit_reason is the user's free-text reason (or the stop/target
 * trigger text when one of those fired). The page should already
 * have shown the user the price they'll be closed at before they
 * click — no surprise fills.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { fetchLatestPrices } from "@/lib/latest-prices";

export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const userReason = typeof body.reason === "string"
    ? body.reason.slice(0, 200)
    : null;

  const sb = getServerClient();
  // Fetch the trade, scoped to this user.
  const { data: trade, error: readErr } = await sb
    .from("paper_trades")
    .select("*")
    .eq("id", id)
    .eq("user_id", userId)
    .maybeSingle();
  if (readErr || !trade) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  if (trade.status !== "open") {
    return NextResponse.json({ error: "already closed" }, { status: 409 });
  }

  // Snapshot the current price as the exit price.
  const prices = await fetchLatestPrices([trade.ticker]);
  const exit_price = prices.get(trade.ticker)?.close ?? null;
  if (exit_price == null) {
    return NextResponse.json(
      { error: "no current price — try again after the next weekly close" },
      { status: 503 },
    );
  }
  let status: "closed_stop" | "closed_target" | "closed_manual";
  let exit_reason: string;
  if (trade.stop_loss != null && exit_price <= Number(trade.stop_loss)) {
    status = "closed_stop";
    exit_reason = userReason ?? "주봉 10MA 손절선 도달";
  } else if (trade.target != null && exit_price >= Number(trade.target)) {
    status = "closed_target";
    exit_reason = userReason ?? "목표가 도달";
  } else {
    status = "closed_manual";
    exit_reason = userReason ?? "수동 청산";
  }

  const { data: closed, error: updErr } = await sb
    .from("paper_trades")
    .update({
      status,
      exit_date: new Date().toISOString().slice(0, 10),
      exit_price,
      exit_reason,
    })
    .eq("id", id)
    .eq("user_id", userId)
    .select()
    .single();
  if (updErr || !closed) {
    console.error("paper_trades close:", updErr?.message);
    return NextResponse.json({ error: "close failed" }, { status: 500 });
  }
  return NextResponse.json({ row: closed });
}
