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

export type SendResult = { ok: true } | { ok: false; reason: string };

export async function sendTelegram(
  chatId: number | string,
  text: string,
): Promise<SendResult> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    // Loud, structured log so Vercel function-logs surface the missing-env
    // case as the root cause instead of a silent "no notification". The
    // bot token is a GitHub Actions secret used by telegram_worker.py;
    // it must ALSO be set in Vercel for site-side notifications.
    console.error(
      "[telegram] TELEGRAM_BOT_TOKEN missing in Vercel env — add it at " +
      "Project Settings → Environment Variables (Production + Preview).",
    );
    return { ok: false, reason: "no-token" };
  }
  try {
    const res = await fetch(`${TELEGRAM_API}${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      console.error(`[telegram] HTTP ${res.status}: ${body.slice(0, 200)}`);
      return { ok: false, reason: `http-${res.status}` };
    }
    return { ok: true };
  } catch (e) {
    console.error("[telegram] fetch threw:", e);
    return { ok: false, reason: "fetch-error" };
  }
}

export type NotifyAdminsResult = {
  attempted: number;
  delivered: number;
  failed: number;
  reason?: string;
};

/**
 * Send the same message to every admin user who's linked Telegram.
 * Used for ops alerts (access requests, feedback submissions) where
 * the user-facing response shouldn't depend on Telegram availability.
 *
 * Each admin gets their own message because Telegram doesn't support
 * broadcast — we just fan out individual sendMessage calls. The return
 * value lets callers (or test endpoints) report on success without
 * scraping function logs.
 */
export async function notifyAdmins(text: string): Promise<NotifyAdminsResult> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("users")
    .select("telegram_chat_id")
    .eq("role", "admin")
    .not("telegram_chat_id", "is", null);
  if (error) {
    console.error("[notifyAdmins] users read:", error.message);
    return { attempted: 0, delivered: 0, failed: 0, reason: "db-error" };
  }
  const chatIds = (data ?? [])
    .map((r) => r.telegram_chat_id as string | null)
    .filter((id): id is string => !!id);
  if (chatIds.length === 0) {
    console.warn(
      "[notifyAdmins] no admins with linked Telegram chat_id — " +
      "promote a user to role='admin' and have them link via /settings → 텔레그램",
    );
    return { attempted: 0, delivered: 0, failed: 0, reason: "no-admins" };
  }
  const results = await Promise.all(
    chatIds.map((id) => sendTelegram(id, text)),
  );
  const delivered = results.filter((r) => r.ok).length;
  const failed = results.length - delivered;
  if (failed > 0) {
    console.warn(
      `[notifyAdmins] ${delivered}/${results.length} delivered. ` +
      `Failure reasons: ${results.filter((r) => !r.ok)
        .map((r) => (r.ok ? "" : r.reason))
        .join(", ")}`,
    );
  }
  return { attempted: chatIds.length, delivered, failed };
}
