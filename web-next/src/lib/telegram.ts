/**
 * Telegram helpers — token consume + sendMessage.
 *
 * Used by the webhook route (/api/telegram/webhook), which receives
 * Telegram Update payloads directly and binds the sender's chat_id to
 * the user via consumeLinkToken().
 */
import { getServerClient } from "@/lib/supabase";

const TOKEN_RE = /^[a-f0-9]{16,48}$/i;
const CHAT_ID_RE = /^-?\d{1,32}$/;

export type ConsumeResult =
  | { ok: true; user_id: string }
  | { ok: false; reason: "invalid_payload" | "unknown_token" | "expired" | "already_used" | "db_error" };

/**
 * Bind a Telegram chat_id to the user identified by `token`.
 * Single source of truth for the token-consume flow.
 */
export async function consumeLinkToken(
  rawToken: string,
  rawChatId: string,
): Promise<ConsumeResult> {
  const token = rawToken.trim();
  const chatId = rawChatId.trim();
  if (!TOKEN_RE.test(token) || !CHAT_ID_RE.test(chatId)) {
    return { ok: false, reason: "invalid_payload" };
  }

  const sb = getServerClient();
  const { data: tok, error: tokErr } = await sb
    .from("telegram_link_tokens")
    .select("token, user_id, expires_at, consumed_at")
    .eq("token", token)
    .maybeSingle();
  if (tokErr) {
    console.error("telegram consume read:", tokErr.message);
    return { ok: false, reason: "db_error" };
  }
  if (!tok) return { ok: false, reason: "unknown_token" };
  if (tok.consumed_at) return { ok: false, reason: "already_used" };
  if (new Date(tok.expires_at).getTime() < Date.now()) {
    return { ok: false, reason: "expired" };
  }

  const { error: updErr } = await sb
    .from("users")
    .update({ telegram_chat_id: chatId, updated_at: new Date().toISOString() })
    .eq("id", tok.user_id);
  if (updErr) {
    console.error("telegram consume update user:", updErr.message);
    return { ok: false, reason: "db_error" };
  }

  await sb
    .from("telegram_link_tokens")
    .update({ consumed_at: new Date().toISOString() })
    .eq("token", token);

  return { ok: true, user_id: tok.user_id as string };
}

const TELEGRAM_API = "https://api.telegram.org/bot";

/**
 * HTML-escape user-controlled content before placing it inside a
 * Telegram parse_mode='HTML' message. Telegram supports a narrow tag
 * subset (`<b>`, `<i>`, `<code>`, etc.); unescaped user input could
 * inject tags or break message rendering.
 *
 * Use in callers when interpolating untrusted strings:
 *   sendTelegram(chat, `Hello ${escapeTgHtml(userName)}`)
 */
export function escapeTgHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export async function sendTelegram(
  chatId: number | string,
  text: string,
): Promise<void> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    console.error("TELEGRAM_BOT_TOKEN missing");
    return;
  }
  try {
    await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
  } catch (e) {
    console.error("sendTelegram failed:", e);
  }
}
