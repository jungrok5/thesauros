/**
 * GET    /api/watchlist            — list current user's watchlist
 * POST   /api/watchlist            — add { ticker, category?, note? }
 * DELETE /api/watchlist?ticker=... — remove by ticker
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { ensureTickerInMaster } from "@/lib/ensure-ticker";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9]{1,12}(\.[A-Z]{1,4})?$/i;
const DATE_RE   = /^\d{4}-\d{2}-\d{2}$/;
const NOTE_MAX  = 500;
const IS_PROD = process.env.NODE_ENV === "production";

/** Map a DB error to a safe response. Real error logged server-side only. */
function dbError(err: { message?: string } | null, fallback = "db error"): NextResponse {
  if (err) console.error("supabase error:", err.message);
  return NextResponse.json(
    { error: fallback, ...(IS_PROD ? {} : { detail: err?.message }) },
    { status: 500 },
  );
}

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
    .from("watchlist")
    .select("id, ticker, category, entry_price, entry_date, note, alerts_enabled, created_at")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) return dbError(error);
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
  const category = (body.category === "holding" ? "holding" : "observing") as
    | "observing"
    | "holding";
  const note = body.note ? String(body.note).slice(0, NOTE_MAX) : null;
  const ep = Number(body.entry_price);
  const entryPrice = Number.isFinite(ep) && ep > 0 ? ep : null;
  const entryDate = body.entry_date && DATE_RE.test(String(body.entry_date))
    ? String(body.entry_date)
    : null;
  const targetPrice = Number.isFinite(Number(body.target_price)) && Number(body.target_price) > 0
    ? Number(body.target_price) : null;
  const targetPct = Number.isFinite(Number(body.target_pct_from_entry))
    ? Number(body.target_pct_from_entry) : null;
  const stopPrice = Number.isFinite(Number(body.stop_price)) && Number(body.stop_price) > 0
    ? Number(body.stop_price) : null;
  const stopPct = Number.isFinite(Number(body.stop_pct_from_entry))
    ? Number(body.stop_pct_from_entry) : null;

  // FK guard: `watchlist.ticker` references `tickers.ticker`. If a user
  // hits this with a ticker that isn't yet in our master (US name
  // resolved via Naver, brand-name fuzzy match, etc.), the FK would
  // 500 the request. Seed the row on demand — Naver lookup pulls the
  // proper Korean display name + market when available.
  await ensureTickerInMaster(ticker);

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();

  // Re-arm 🎯 target / 🛑 stop alerts when the user actually changed the
  // threshold. Without this, telegram_worker's one-shot `*_hit_at`
  // marker would silently suppress alerts at the new level.
  const { data: existing } = await sb
    .from("watchlist")
    .select("target_price, target_pct_from_entry, stop_price, stop_pct_from_entry")
    .eq("user_id", userId)
    .eq("ticker", ticker)
    .maybeSingle();
  const resetTarget =
    existing != null &&
    (Number(existing.target_price) !== Number(targetPrice) ||
      Number(existing.target_pct_from_entry) !== Number(targetPct));
  const resetStop =
    existing != null &&
    (Number(existing.stop_price) !== Number(stopPrice) ||
      Number(existing.stop_pct_from_entry) !== Number(stopPct));

  const payload: Record<string, unknown> = {
    user_id: userId, ticker, category, note,
    entry_price: entryPrice, entry_date: entryDate,
    target_price: targetPrice,
    target_pct_from_entry: targetPct,
    stop_price: stopPrice,
    stop_pct_from_entry: stopPct,
  };
  if (resetTarget) payload.target_hit_at = null;
  if (resetStop) payload.stop_hit_at = null;

  const { data, error } = await sb
    .from("watchlist")
    .upsert(payload, { onConflict: "user_id,ticker" })
    .select()
    .single();
  if (error) return dbError(error);
  return NextResponse.json({ item: data });
}

export async function DELETE(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const url = new URL(req.url);
  const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { error } = await sb
    .from("watchlist")
    .delete()
    .eq("user_id", userId)
    .eq("ticker", ticker);
  if (error) return dbError(error);
  return NextResponse.json({ ok: true });
}
