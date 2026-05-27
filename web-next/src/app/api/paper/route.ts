/**
 * /api/paper — list & create paper positions for the logged-in user.
 *
 *   GET     ?status=open|all
 *   POST    body: {
 *     ticker, amount_krw, entry_price,
 *     stop_loss?, target?, notes?
 *   }
 *
 * Broker-standard schema (2026-05-27 reform): a POSITION represents
 * the user's stake in a ticker; every buy/sell becomes a FILL row.
 *
 * POST behavior:
 *   · If the user has an open position on this ticker → adds a BUY
 *     fill (추매) and updates the position's aggregates.
 *   · Otherwise → creates a new position + first BUY fill.
 *
 * 2026-05-27 — does NOT touch watchlist. Earlier the route auto-
 * upserted a `category='holding'` row "so pattern alerts start
 * firing", which conflated 모의투자 (simulation) with the watchlist
 * 보유 list and made paper positions show up in the holdings UI.
 * Paper has its own alerts (initial_stop_loss / target via
 * notify_paper_alerts). If a user wants enter/warn/exit/pyramid
 * pattern alerts on a paper-bought ticker, they explicitly add it
 * to watchlist from the stock detail page.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import {
  fetchOpenPositions, fetchAllPositions,
  fetchOpenPositionForTicker, computeStats,
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
    ? await fetchAllPositions(userId)
    : await fetchOpenPositions(userId);
  return NextResponse.json({ positions: rows, stats: computeStats(rows) });
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
    ? body.ticker.trim().toUpperCase() : "";
  const amount_krw = Number(body.amount_krw);
  const entry_price = Number(body.entry_price);
  const stop_loss = body.stop_loss != null ? Number(body.stop_loss) : null;
  const target = body.target != null ? Number(body.target) : null;
  const notes = typeof body.notes === "string"
    ? body.notes.slice(0, 500) : null;

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
  if (stop_loss != null && stop_loss >= entry_price) {
    return NextResponse.json(
      { error: "stop_loss must be < entry_price" }, { status: 400 });
  }
  if (target != null && target <= entry_price) {
    return NextResponse.json(
      { error: "target must be > entry_price" }, { status: 400 });
  }

  const sb = getServerClient();
  const shares = amount_krw / entry_price;
  const existing = await fetchOpenPositionForTicker(userId, ticker);

  let positionId: string;
  if (existing) {
    // 추매 — bump aggregates on the existing position.
    positionId = existing.id;
    const newShares = Number(existing.shares_open) + shares;
    const newInvested = Number(existing.total_invested_krw) + amount_krw;
    const { error: upErr } = await sb
      .from("paper_positions")
      .update({
        shares_open: newShares,
        total_invested_krw: newInvested,
      })
      .eq("id", positionId)
      .eq("user_id", userId);
    if (upErr) {
      console.error("paper_positions update (pyramid):", upErr.message);
      return NextResponse.json(
        { error: "추매 실패" }, { status: 500 });
    }
  } else {
    const { data, error } = await sb
      .from("paper_positions")
      .insert({
        user_id: userId,
        ticker,
        status: "open",
        shares_open: shares,
        total_invested_krw: amount_krw,
        realized_pnl_krw: 0,
        initial_entry_price: entry_price,
        initial_stop_loss: stop_loss,
        initial_target: target,
        notes,
      })
      .select()
      .single();
    if (error || !data) {
      console.error("paper_positions insert:", error?.message);
      return NextResponse.json(
        { error: "insert failed" }, { status: 500 });
    }
    positionId = data.id;
  }

  const { error: fillErr } = await sb
    .from("paper_fills")
    .insert({
      position_id: positionId,
      user_id: userId,
      side: "buy",
      fill_price: entry_price,
      shares,
      amount_krw,
      stop_loss,
      target,
      reason: existing ? "추매" : "매수",
    });
  if (fillErr) {
    console.error("paper_fills insert (buy):", fillErr.message);
    return NextResponse.json({ error: "fill insert failed" }, { status: 500 });
  }

  return NextResponse.json({ position_id: positionId, side: "buy" });
}
