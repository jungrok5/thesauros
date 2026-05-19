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
import { notifyAdmins } from "@/lib/telegram";
import { formatFeedbackNotification } from "@/lib/admin-notifications";
import { parseFeedbackInput } from "@/lib/feedback-validation";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await req.json().catch(() => ({}));
  const parsed = parseFeedbackInput(body);
  if (!parsed.ok) {
    return NextResponse.json({ error: parsed.error }, { status: 400 });
  }

  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
  const userEmail = session.user.email.toLowerCase();
  const userAgent = req.headers.get("user-agent")?.slice(0, 500) ?? null;

  const sb = getServerClient();
  const { data, error } = await sb
    .from("feedback")
    .insert({
      user_id: userId,
      user_email: userEmail,
      category: parsed.category,
      title: parsed.title,
      body: parsed.body,
      page_url: parsed.pageUrl,
      user_agent: userAgent,
    })
    .select("id")
    .single();
  if (error || !data) {
    console.error("feedback insert:", error?.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  void notifyAdmins(
    formatFeedbackNotification({
      id: data.id,
      category: parsed.category,
      title: parsed.title,
      body: parsed.body,
      userEmail,
    }),
  );

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
