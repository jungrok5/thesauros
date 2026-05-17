/**
 * POST /api/telegram/webhook
 *   Receives Telegram Bot API updates (set this URL via BotFather
 *   /setwebhook). No long-poll worker needed. See DEPLOY.md §5.
 *
 *   Security: Telegram includes the secret_token (registered with
 *   setWebhook) in the X-Telegram-Bot-Api-Secret-Token header. We
 *   timing-safe compare against TELEGRAM_WEBHOOK_SECRET.
 *
 *   Handled commands:
 *     /start, /help     →  reply with usage
 *     /link <token>     →  consume the token + bind chat_id
 *     /unlink           →  point user to /settings/alerts
 *     (anything else)   →  reply with help
 */
import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";
import { consumeLinkToken, sendTelegram } from "@/lib/telegram";

export const dynamic = "force-dynamic";

const HELP_TEXT =
  "👋 Thesauros 캔들 추세 봇\n\n" +
  "사용법:\n" +
  "  /link &lt;토큰&gt;  — 웹사이트 /settings/alerts 에서 발급한 토큰 입력\n" +
  "  /unlink        — 이 채팅의 알림 구독 해제 (웹사이트에서)\n" +
  "  /help          — 도움말";

function constEq(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

type TgMessage = {
  message_id?: number;
  chat?: { id?: number };
  text?: string;
};

type TgUpdate = {
  update_id?: number;
  message?: TgMessage;
};

async function handleLink(chatId: number, token: string) {
  const result = await consumeLinkToken(token, String(chatId));
  if (result.ok) {
    await sendTelegram(
      chatId,
      "✅ 연동 완료!\n이제 관심 종목 신호가 이 채팅으로 옵니다.\n" +
        "/settings/alerts 에서 알림 종류를 세분화할 수 있습니다.",
    );
    return;
  }
  const messages: Record<string, string> = {
    invalid_payload: "❌ 토큰 형식이 잘못됐습니다.",
    unknown_token: "❌ 알 수 없는 토큰입니다. 웹사이트에서 다시 발급하세요.",
    expired: "❌ 만료된 토큰입니다. 새로 발급해주세요.",
    already_used: "❌ 이미 사용된 토큰입니다.",
    db_error: "❌ 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
  };
  await sendTelegram(chatId, messages[result.reason] ?? "❌ 연동 실패.");
}

async function handleMessage(msg: TgMessage): Promise<void> {
  const chatId = msg.chat?.id;
  const text = (msg.text ?? "").trim();
  if (!chatId || !text) return;

  if (text.startsWith("/start") || text.startsWith("/help")) {
    await sendTelegram(chatId, HELP_TEXT);
    return;
  }
  if (text.startsWith("/link")) {
    const parts = text.split(/\s+/, 2);
    if (parts.length < 2 || parts[1].length < 8) {
      await sendTelegram(chatId, "사용법: <code>/link &lt;토큰&gt;</code>");
      return;
    }
    await handleLink(chatId, parts[1]);
    return;
  }
  if (text.startsWith("/unlink")) {
    await sendTelegram(
      chatId,
      "웹사이트 /settings/alerts 의 '해제' 버튼을 눌러주세요.",
    );
    return;
  }
  await sendTelegram(chatId, HELP_TEXT);
}

export async function POST(req: NextRequest) {
  const secret = process.env.TELEGRAM_WEBHOOK_SECRET;
  if (!secret) {
    console.error("TELEGRAM_WEBHOOK_SECRET missing");
    return NextResponse.json({ error: "not configured" }, { status: 500 });
  }
  const got = req.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!got || !constEq(got, secret)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  let update: TgUpdate = {};
  try {
    update = (await req.json()) as TgUpdate;
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  // Telegram expects 200 OK quickly — handle async but await our send
  // so the chat gets the reply before the function exits.
  if (update.message) {
    try {
      await handleMessage(update.message);
    } catch (e) {
      console.error("webhook handleMessage:", e);
    }
  }

  return NextResponse.json({ ok: true });
}
