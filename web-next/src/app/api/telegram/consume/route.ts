/**
 * POST /api/telegram/consume
 *   Called by the Telegram bot worker (not by the browser). Looks up an
 *   unexpired, unconsumed link token, stamps the user's `telegram_chat_id`,
 *   and marks the token consumed. Authenticated via a shared secret in the
 *   `x-bot-secret` header (TELEGRAM_LINK_SECRET).
 *
 * Body: { token: string, chat_id: string }
 */
import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TOKEN_RE = /^[a-f0-9]{16,48}$/i;
const CHAT_ID_RE = /^-?\d{1,32}$/;

function constEq(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

export async function POST(req: NextRequest) {
  const secret = process.env.TELEGRAM_LINK_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "server not configured" }, { status: 500 });
  }
  const given = req.headers.get("x-bot-secret") ?? "";
  if (!given || !constEq(given, secret)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const body = await req.json().catch(() => ({}));
  const token = String(body.token ?? "").trim();
  const chatId = String(body.chat_id ?? "").trim();
  if (!TOKEN_RE.test(token) || !CHAT_ID_RE.test(chatId)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const sb = getServerClient();
  const { data: tok, error: tokErr } = await sb
    .from("telegram_link_tokens")
    .select("token, user_id, expires_at, consumed_at")
    .eq("token", token)
    .maybeSingle();
  if (tokErr) {
    console.error("telegram consume read:", tokErr.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  if (!tok) {
    return NextResponse.json({ error: "unknown token" }, { status: 404 });
  }
  if (tok.consumed_at) {
    return NextResponse.json({ error: "already used" }, { status: 410 });
  }
  if (new Date(tok.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "expired" }, { status: 410 });
  }

  const { error: updErr } = await sb
    .from("users")
    .update({ telegram_chat_id: chatId, updated_at: new Date().toISOString() })
    .eq("id", tok.user_id);
  if (updErr) {
    console.error("telegram consume update user:", updErr.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  await sb
    .from("telegram_link_tokens")
    .update({ consumed_at: new Date().toISOString() })
    .eq("token", token);

  return NextResponse.json({ ok: true, user_id: tok.user_id });
}
