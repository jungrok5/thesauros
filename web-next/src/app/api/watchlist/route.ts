/**
 * GET    /api/watchlist            — list current user's watchlist
 * POST   /api/watchlist            — add { ticker, category?, note? }
 * DELETE /api/watchlist?ticker=... — remove by ticker
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

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
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ items: data });
}

export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim();
  if (!ticker) return NextResponse.json({ error: "ticker required" }, { status: 400 });
  const category = (body.category === "holding" ? "holding" : "observing") as
    | "observing"
    | "holding";
  const note = body.note ? String(body.note) : null;
  const entryPrice = body.entry_price != null ? Number(body.entry_price) : null;
  const entryDate = body.entry_date ? String(body.entry_date) : null;

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist")
    .upsert(
      { user_id: userId, ticker, category, note, entry_price: entryPrice, entry_date: entryDate },
      { onConflict: "user_id,ticker" },
    )
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ item: data });
}

export async function DELETE(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const url = new URL(req.url);
  const ticker = url.searchParams.get("ticker") ?? "";
  if (!ticker) return NextResponse.json({ error: "ticker required" }, { status: 400 });

  const userId = await ensureUserId(user.email, user.name);
  const sb = getServerClient();
  const { error } = await sb
    .from("watchlist")
    .delete()
    .eq("user_id", userId)
    .eq("ticker", ticker);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
