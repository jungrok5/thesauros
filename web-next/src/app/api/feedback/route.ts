/**
 * /api/feedback — user-submitted bug reports + feature suggestions.
 *
 *   POST  body: { category: 'bug'|'feature'|'other', title, body, page_url? }
 *      Inserts a row owned by the user, fans out a Telegram notification
 *      to every admin who's linked their chat_id.
 *
 *   GET   list of the caller's own submissions (with statuses).
 *
 * Admin operations live in /api/admin/feedback (role-gated).
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { escapeTgHtml, notifyAdmins } from "@/lib/telegram";

export const dynamic = "force-dynamic";

const TITLE_MAX = 120;
const BODY_MAX = 4000;
const URL_MAX = 500;
const VALID_CATEGORIES = new Set(["bug", "feature", "other"]);

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const userEmail = session.user.email.toLowerCase();

  const body = await req.json().catch(() => ({}));
  const category = String(body.category ?? "").trim();
  const title = String(body.title ?? "").trim().slice(0, TITLE_MAX);
  const text = String(body.body ?? "").trim().slice(0, BODY_MAX);
  const pageUrl = body.page_url
    ? String(body.page_url).slice(0, URL_MAX)
    : null;
  const userAgent = req.headers.get("user-agent")?.slice(0, 500) ?? null;

  if (!VALID_CATEGORIES.has(category)) {
    return NextResponse.json({ error: "invalid category" }, { status: 400 });
  }
  if (!title || !text) {
    return NextResponse.json({ error: "missing title or body" }, { status: 400 });
  }

  const sb = getServerClient();
  const { data, error } = await sb
    .from("feedback")
    .insert({
      user_id: userId,
      user_email: userEmail,
      category,
      title,
      body: text,
      page_url: pageUrl,
      user_agent: userAgent,
    })
    .select("id")
    .single();
  if (error || !data) {
    console.error("feedback insert:", error?.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  const labelByCat: Record<string, string> = {
    bug: "🐛 버그",
    feature: "💡 건의",
    other: "💬 기타",
  };
  const tg =
    `${labelByCat[category] ?? category} #${data.id}\n` +
    `<b>${escapeTgHtml(title)}</b>\n` +
    `from ${escapeTgHtml(userEmail)}\n` +
    `\n` +
    `${escapeTgHtml(text.slice(0, 600))}` +
    (text.length > 600 ? "…" : "") +
    `\n\n→ /admin/feedback`;
  void notifyAdmins(tg);

  return NextResponse.json({ ok: true, id: data.id });
}

export async function GET() {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const sb = getServerClient();
  const { data, error } = await sb
    .from("feedback")
    .select("id, category, title, status, created_at, updated_at, admin_notes")
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .limit(50);
  if (error) {
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  return NextResponse.json({ items: data ?? [] });
}
