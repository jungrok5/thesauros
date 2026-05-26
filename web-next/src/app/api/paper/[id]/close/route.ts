/**
 * POST /api/paper/[id]/close   (id = paper_positions.id)
 *
 *   body: {
 *     reason?:        string,
 *     partial_pct?:   number,    // 0..1 — partial close fraction
 *   }
 *
 * Adds a SELL fill on the position at the current weekly close.
 * Position aggregates update:
 *   · shares_open       -= sold_shares
 *   · realized_pnl_krw  += (sell_price - avg_cost) × sold_shares
 *   · status flips to 'closed' when shares_open hits 0.
 *
 * Routing on status_at_fill follows the same stop/target check as
 * before (closed_stop / closed_target / closed_manual) — applied
 * to the fill, not the position.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { fetchLatestPrices } from "@/lib/latest-prices";
import type { PaperFillRow } from "@/lib/paper-trades";

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
    ? body.reason.slice(0, 200) : null;
  const partial_pct = body.partial_pct != null ? Number(body.partial_pct) : 1;
  if (!Number.isFinite(partial_pct) || partial_pct <= 0 || partial_pct > 1) {
    return NextResponse.json(
      { error: "partial_pct must be in (0, 1]" }, { status: 400 });
  }

  const sb = getServerClient();
  const { data: position, error: readErr } = await sb
    .from("paper_positions")
    .select("*")
    .eq("id", id)
    .eq("user_id", userId)
    .maybeSingle();
  if (readErr || !position) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  if (position.status !== "open" || Number(position.shares_open) <= 0) {
    return NextResponse.json({ error: "already closed" }, { status: 409 });
  }

  const prices = await fetchLatestPrices([position.ticker]);
  const sell_price = prices.get(position.ticker)?.close ?? null;
  if (sell_price == null) {
    return NextResponse.json(
      { error: "no current price — try again after the next weekly close" },
      { status: 503 },
    );
  }

  // Compute avg_cost from buy fills minus sell fills (weighted-average
  // FIFO of unsold shares — proportional cost basis removal).
  const { data: fillRows, error: fillsErr } = await sb
    .from("paper_fills")
    .select("*")
    .eq("position_id", id)
    .order("fill_date", { ascending: true });
  if (fillsErr) {
    console.error("paper_fills read:", fillsErr.message);
    return NextResponse.json({ error: "fills read failed" }, { status: 500 });
  }
  let costRemaining = 0;
  let sharesRemaining = 0;
  for (const f of (fillRows ?? []) as PaperFillRow[]) {
    if (f.side === "buy") {
      costRemaining += Number(f.amount_krw);
      sharesRemaining += Number(f.shares);
    } else {
      if (sharesRemaining > 0) {
        const ratio = Math.min(1, Number(f.shares) / sharesRemaining);
        costRemaining -= costRemaining * ratio;
        sharesRemaining -= Number(f.shares);
      }
    }
  }
  if (sharesRemaining <= 0) {
    return NextResponse.json({ error: "no open shares to close" }, { status: 409 });
  }
  const avg_cost = costRemaining / sharesRemaining;

  // How many shares are being sold in this fill?
  const sold_shares = sharesRemaining * partial_pct;
  const sold_amount = sell_price * sold_shares;
  const cost_of_sold = avg_cost * sold_shares;
  const pnl_krw = sold_amount - cost_of_sold;
  const pnl_pct = (sell_price / avg_cost - 1) * 100;

  // Routing based on initial plan thresholds (book-spirit gates).
  let status_at_fill: "closed_stop" | "closed_target" | "closed_manual";
  let reason: string;
  const initStop = position.initial_stop_loss != null
    ? Number(position.initial_stop_loss) : null;
  const initTarget = position.initial_target != null
    ? Number(position.initial_target) : null;
  if (initStop != null && sell_price <= initStop) {
    status_at_fill = "closed_stop";
    reason = userReason ?? "주봉 10MA 손절선 도달";
  } else if (initTarget != null && sell_price >= initTarget) {
    status_at_fill = "closed_target";
    reason = userReason ?? "목표가 도달";
  } else {
    status_at_fill = "closed_manual";
    reason = userReason
      ?? (partial_pct < 1
            ? `분할 매도 (${Math.round(partial_pct * 100)}%)`
            : "수동 청산");
  }

  // 1) Insert the sell fill.
  const { error: insErr } = await sb
    .from("paper_fills")
    .insert({
      position_id: id,
      user_id: userId,
      side: "sell",
      fill_price: sell_price,
      shares: sold_shares,
      amount_krw: sold_amount,
      pnl_krw,
      pnl_pct,
      status_at_fill,
      reason,
    });
  if (insErr) {
    console.error("paper_fills insert (sell):", insErr.message);
    return NextResponse.json(
      { error: "sell fill insert failed" }, { status: 500 });
  }

  // 2) Update the position's aggregates. shares_open becomes
  // remaining shares; realized_pnl accumulates the realized portion.
  const new_shares = sharesRemaining - sold_shares;
  const new_realized = Number(position.realized_pnl_krw) + pnl_krw;
  const newStatus: "open" | "closed" = new_shares <= 1e-9 ? "closed" : "open";
  const update: Record<string, unknown> = {
    shares_open: new_shares,
    realized_pnl_krw: new_realized,
    status: newStatus,
  };
  if (newStatus === "closed") update.closed_at = new Date().toISOString();
  const { error: posErr } = await sb
    .from("paper_positions")
    .update(update)
    .eq("id", id)
    .eq("user_id", userId);
  if (posErr) {
    console.error("paper_positions update (after sell):", posErr.message);
    return NextResponse.json(
      { error: "position update failed" }, { status: 500 });
  }

  return NextResponse.json({
    position_id: id,
    side: "sell",
    partial: partial_pct < 1,
    sell_price,
    pnl_krw,
    pnl_pct,
    status_at_fill,
    position_closed: newStatus === "closed",
  });
}
