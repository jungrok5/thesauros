/**
 * POST /api/telegram/consume
 *   Legacy endpoint, called by the long-poll bot (app.db.telegram_bot).
 *   Webhook deployments don't need this route — they call
 *   `consumeLinkToken()` directly inside /api/telegram/webhook.
 *
 *   Authenticated via shared secret `x-bot-secret` header
 *   (TELEGRAM_LINK_SECRET).
 *
 * Body: { token: string, chat_id: string }
 */
import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";
import { consumeLinkToken } from "@/lib/telegram";

export const dynamic = "force-dynamic";

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
  const result = await consumeLinkToken(
    String(body.token ?? ""),
    String(body.chat_id ?? ""),
  );
  if (result.ok) {
    return NextResponse.json({ ok: true, user_id: result.user_id });
  }
  const statusByReason: Record<string, number> = {
    invalid_payload: 400,
    unknown_token: 404,
    expired: 410,
    already_used: 410,
    db_error: 500,
  };
  return NextResponse.json(
    { error: result.reason },
    { status: statusByReason[result.reason] ?? 500 },
  );
}
