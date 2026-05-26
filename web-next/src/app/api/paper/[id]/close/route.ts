/**
 * POST /api/paper/[id]/close
 *
 *  body: {
 *    reason?:     string,                          // free-text exit reason
 *    partial_pct?: number,                         // 0..1 inclusive — partial sell
 *  }
 *
 * Full close (default — no partial_pct or 1.0):
 *   Marks the row closed at the latest weekly close. status routing:
 *     · current_price <= stop_loss → "closed_stop"
 *     · current_price >= target    → "closed_target"
 *     · else                       → "closed_manual"
 *
 * Partial close (0 < partial_pct < 1):
 *   Phase 4 "분할 매도 / 익절". Splits the row:
 *     · existing row: shares × (1 - partial_pct), amount_krw scaled too,
 *       stays status='open' (continues running with smaller size)
 *     · new row:      shares × partial_pct, immediately closed at the
 *       current price with status routing as above
 *   So /paper now reports the realized partial P&L (via the new closed
 *   row) AND the remaining open lot — same as a real broker after a
 *   partial fill.
 *
 * exit_reason is the user's free-text reason (or the stop/target
 * trigger text when one of those fired).
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
  // 0 < partial_pct < 1 splits the row; null/undefined/1 means full close.
  const partial_pct = body.partial_pct != null ? Number(body.partial_pct) : 1;
  if (!Number.isFinite(partial_pct) || partial_pct <= 0 || partial_pct > 1) {
    return NextResponse.json(
      { error: "partial_pct must be in (0, 1]" }, { status: 400 });
  }

  const sb = getServerClient();
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

  // ─── Full close (partial_pct == 1) — original code path ───────────
  if (partial_pct >= 1) {
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
    return NextResponse.json({ row: closed, partial: false });
  }

  // ─── Partial close — split the row ────────────────────────────────
  // Original lot's shares × partial_pct gets a new immediately-closed
  // row, the existing row shrinks to (1 - partial_pct) of its size.
  const closedShares = Number(trade.shares) * partial_pct;
  const closedAmount = Number(trade.amount_krw) * partial_pct;
  const remainingShares = Number(trade.shares) - closedShares;
  const remainingAmount = Number(trade.amount_krw) - closedAmount;

  // 1) shrink the existing open row
  const { error: shrinkErr } = await sb
    .from("paper_trades")
    .update({
      shares: remainingShares,
      amount_krw: remainingAmount,
    })
    .eq("id", id)
    .eq("user_id", userId);
  if (shrinkErr) {
    console.error("paper_trades partial shrink:", shrinkErr.message);
    return NextResponse.json(
      { error: "partial close shrink failed" }, { status: 500 });
  }

  // 2) insert the new closed row that captures the partial fill
  const { data: closedRow, error: insErr } = await sb
    .from("paper_trades")
    .insert({
      user_id: userId,
      ticker: trade.ticker,
      entry_date: trade.entry_date,                  // same entry, partial exit
      entry_price: trade.entry_price,
      amount_krw: closedAmount,
      shares: closedShares,
      stop_loss: trade.stop_loss,
      target: trade.target,
      notes: trade.notes
        ? `${trade.notes} · 분할 매도 (${Math.round(partial_pct * 100)}%)`
        : `분할 매도 (${Math.round(partial_pct * 100)}%)`,
      status,
      exit_date: new Date().toISOString().slice(0, 10),
      exit_price,
      exit_reason,
    })
    .select()
    .single();
  if (insErr || !closedRow) {
    // Best-effort revert of the shrink so the user's open size is
    // restored. (Two-step write — Supabase has no first-class
    // transaction over PostgREST. If the revert itself fails, log
    // loudly so we can manually reconcile.)
    console.error("paper_trades partial insert:", insErr?.message);
    const { error: revertErr } = await sb
      .from("paper_trades")
      .update({
        shares: trade.shares,
        amount_krw: trade.amount_krw,
      })
      .eq("id", id)
      .eq("user_id", userId);
    if (revertErr) {
      console.error("paper_trades partial revert FAILED:",
                    revertErr.message, "trade_id:", id);
    }
    return NextResponse.json(
      { error: "partial close insert failed" }, { status: 500 });
  }
  return NextResponse.json({ row: closedRow, partial: true });
}
