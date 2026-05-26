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

  // Pyramiding (추매) is allowed — every new buy on the same ticker
  // becomes a separate lot with its own entry_price / stop / target.
  // Phase 4 reform (2026-05-27): the old double-buy guard prevented
  // 책 정신's "물타기 X, 불타기 O" — adding to a winning position is
  // a deliberate move, not an accident. To prevent fat-finger
  // duplicates, the modal surfaces the existing open lots before
  // confirm (client-side responsibility, see PaperBuyButton).
  void fetchOpenForUserTicker;  // kept import for future per-ticker UI

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

  // 모의 투자 = 시스템 신호 측면에서 "보유 종목" 과 동등하게 다룸.
  // watchlist 에 'holding' 카테고리로 UPSERT 해서 telegram_worker 의
  // enter/exit/warn/pyramid alert 가 자동으로 발사되게 함. paper-specific
  // 손절/목표 도달 알림은 notify_paper_alerts 가 별도로 처리 (watchlist
  // target/stop column 은 채우지 않음 — paper_trades.stop_loss/target 이
  // single source of truth).
  const { error: watchErr } = await sb
    .from("watchlist")
    .upsert(
      {
        user_id: userId,
        ticker,
        category: "holding",
        alerts_enabled: true,
        last_accessed_at: new Date().toISOString(),
      },
      { onConflict: "user_id,ticker" },
    );
  if (watchErr) {
    // Non-fatal — paper trade is already saved. Telegram integration
    // can self-heal later (e.g. user adds the ticker to watchlist
    // manually) but log it so we notice if this is a systemic failure.
    console.error("watchlist upsert from paper buy:", watchErr.message);
  }
  return NextResponse.json({ row: data });
}
