/**
 * POST /api/admin/test-telegram — admin-only smoke test.
 *
 * Sends a "[테스트] Thesauros 알림 작동" message to every linked admin
 * chat_id and returns the `notifyAdmins` result so the admin can tell
 * from the UI whether:
 *   - `TELEGRAM_BOT_TOKEN` is wired into Vercel env
 *   - any admin user actually has telegram_chat_id linked
 *   - Telegram API is reachable + accepting the bot
 *
 * Without this, the only diagnostic is the Vercel function logs.
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { notifyAdmins } from "@/lib/telegram";

export const dynamic = "force-dynamic";

export async function POST() {
  const session = await auth();
  const u = session?.user as { role?: string; email?: string } | undefined;
  if (!u?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (u.role !== "admin") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  const result = await notifyAdmins(
    `🧪 <b>Thesauros 알림 테스트</b>\n` +
    `${new Date().toISOString()}\n` +
    `발신자: ${u.email}`,
  );
  return NextResponse.json(result);
}
