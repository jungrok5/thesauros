/**
 * Pure formatters for admin-bound Telegram notifications.
 *
 * Keeping the message construction here (not inline in the route
 * handlers) lets us unit-test the wording, HTML escaping, and
 * truncation without spinning up a fake auth/supabase context.
 *
 * The actual `notifyAdmins(text)` send-side lives in lib/telegram.ts;
 * route handlers compose a message with these helpers, then fire-and-
 * forget that helper.
 */
import { escapeTgHtml } from "@/lib/telegram";

export const FEEDBACK_CATEGORY_LABELS: Record<string, string> = {
  bug: "🐛 버그",
  feature: "💡 건의",
  other: "💬 기타",
};

/** Telegram message body for a new access request. */
export function formatAccessRequestNotification(
  email: string,
  name: string | null,
  reason: string | null,
): string {
  const emailE = escapeTgHtml(email);
  const nameE = name ? escapeTgHtml(name) : null;
  const reasonE = reason ? escapeTgHtml(reason) : "(사유 없음)";
  // The angle brackets around email need to be HTML entities, not raw,
  // otherwise Telegram's HTML parser truncates the message at the first
  // unescaped '<'.
  return (
    `🆕 <b>접근 요청</b>\n` +
    `${nameE ? `${nameE} ` : ""}&lt;${emailE}&gt;\n` +
    `\n` +
    `<i>${reasonE}</i>\n` +
    `\n` +
    `→ /admin/access 에서 승인/거절`
  );
}

const FEEDBACK_BODY_PREVIEW_MAX = 600;

/** Telegram message body for a new feedback ticket. */
export function formatFeedbackNotification(args: {
  id: number;
  category: string;
  title: string;
  body: string;
  userEmail: string;
}): string {
  const { id, category, title, body, userEmail } = args;
  const catLabel = FEEDBACK_CATEGORY_LABELS[category] ?? category;
  const titleE = escapeTgHtml(title);
  const emailE = escapeTgHtml(userEmail);
  const preview =
    body.length > FEEDBACK_BODY_PREVIEW_MAX
      ? body.slice(0, FEEDBACK_BODY_PREVIEW_MAX) + "…"
      : body;
  const previewE = escapeTgHtml(preview);
  return (
    `${catLabel} #${id}\n` +
    `<b>${titleE}</b>\n` +
    `from ${emailE}\n` +
    `\n` +
    `${previewE}\n\n→ /admin/feedback`
  );
}
