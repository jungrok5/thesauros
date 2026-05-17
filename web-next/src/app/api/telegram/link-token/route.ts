/**
 * POST /api/telegram/link-token
 *   Issues a one-time, 1-hour link token for the current user. User pastes
 *   "/link <token>" to the bot, which then calls /api/telegram/consume
 *   (with the shared TELEGRAM_LINK_SECRET) to write `telegram_chat_id`.
 *
 * GET  /api/telegram/link-token
 *   Returns the current user's most recent unexpired token (if any), so the
 *   settings page can display it on refresh without forcing re-issue.
 */
import { NextResponse } from "next/server";
import { randomBytes } from "node:crypto";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

function genToken(): string {
  // 32 hex chars (128 bits) — well within VARCHAR(48).
  return randomBytes(16).toString("hex");
}

async function currentUserId(): Promise<string | null> {
  const session = await auth();
  if (!session?.user?.email) return null;
  return await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
}

export async function POST() {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const sb = getServerClient();
  const token = genToken();
  const expiresAt = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  const { error } = await sb.from("telegram_link_tokens").insert({
    token,
    user_id: userId,
    expires_at: expiresAt,
  });
  if (error) {
    console.error("telegram_link_tokens insert:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({
    token,
    expires_at: expiresAt,
    instructions:
      "텔레그램 @candle_trend_bot 에 /link " + token + " 를 보내세요.",
  });
}

export async function DELETE() {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const sb = getServerClient();
  const { error } = await sb
    .from("users")
    .update({ telegram_chat_id: null, updated_at: new Date().toISOString() })
    .eq("id", userId);
  if (error) {
    console.error("telegram disconnect:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}

export async function GET() {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const sb = getServerClient();
  const { data, error } = await sb
    .from("telegram_link_tokens")
    .select("token, expires_at, consumed_at")
    .eq("user_id", userId)
    .is("consumed_at", null)
    .gt("expires_at", new Date().toISOString())
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("telegram_link_tokens read:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ active: data ?? null });
}
