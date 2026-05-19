/**
 * GET  /api/access-request   — current user's access state + last request
 * POST /api/access-request   — submit/update access request (body: { reason })
 *
 * Any logged-in user can call this; the proxy lets it through even for
 * pending/rejected accounts.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { notifyAdmins } from "@/lib/telegram";
import { formatAccessRequestNotification } from "@/lib/admin-notifications";

export const dynamic = "force-dynamic";

const REASON_MAX = 500;

async function currentUserId(): Promise<string | null> {
  const session = await auth();
  if (!session?.user?.email) return null;
  return await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
}

export async function GET() {
  const userId = await currentUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const sb = getServerClient();
  const [{ data: user }, { data: req }] = await Promise.all([
    sb.from("users").select("access_status, role").eq("id", userId).maybeSingle(),
    sb
      .from("access_requests")
      .select("reason, requested_at, decided_at, decision, note")
      .eq("user_id", userId)
      .maybeSingle(),
  ]);
  return NextResponse.json({
    status: user?.access_status ?? "pending",
    role: user?.role ?? "user",
    request: req ?? null,
  });
}

export async function POST(req: NextRequest) {
  const session = await auth();
  const userId = await currentUserId();
  if (!userId || !session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const reason = body.reason
    ? String(body.reason).slice(0, REASON_MAX)
    : null;

  const sb = getServerClient();
  const { error } = await sb
    .from("access_requests")
    .upsert(
      {
        user_id: userId,
        reason,
        requested_at: new Date().toISOString(),
        decided_at: null,
        decision: null,
        decided_by: null,
        note: null,
      },
      { onConflict: "user_id" },
    );
  if (error) {
    console.error("access_request upsert:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  // Telegram-notify admins so they can triage in /admin/access. Fire-
  // and-forget — never blocks the user's response on Telegram delivery.
  void notifyAdmins(
    formatAccessRequestNotification(
      session.user.email,
      session.user.name ?? null,
      reason,
    ),
  );

  return NextResponse.json({ ok: true });
}
