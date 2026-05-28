/**
 * /api/admin/feedback/[id] — admin-only status + notes mutation.
 *
 *   PATCH  body: { status?, admin_notes? }
 *      Update the ticket. Role check happens here in addition to the
 *      proxy gate so a misconfigured proxy doesn't accidentally open
 *      this surface.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";

export const dynamic = "force-dynamic";

const VALID_STATUS = new Set(["open", "in_progress", "resolved", "wont_fix"]);
const NOTES_MAX = 2000;

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  const u = session?.user as { role?: string; email?: string } | undefined;
  if (!u?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  // 2026-05-28 — re-read role from DB, not just session JWT. A user
  // demoted from admin would otherwise retain admin powers until their
  // JWT refreshes (NextAuth caches role in the session token).
  const sbCheck = getServerClient();
  const { data: live } = await sbCheck
    .from("users")
    .select("role")
    .eq("email", u.email.toLowerCase())
    .maybeSingle();
  if (live?.role !== "admin") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const { id: idStr } = await params;
  const id = parseInt(idStr, 10);
  if (!Number.isFinite(id) || id <= 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }

  const body = await req.json().catch(() => ({}));
  const patch: { status?: string; admin_notes?: string | null } = {};
  if (body.status !== undefined) {
    const s = String(body.status);
    if (!VALID_STATUS.has(s)) {
      return NextResponse.json({ error: "invalid status" }, { status: 400 });
    }
    patch.status = s;
  }
  if (body.admin_notes !== undefined) {
    patch.admin_notes = body.admin_notes
      ? String(body.admin_notes).slice(0, NOTES_MAX)
      : null;
  }
  if (Object.keys(patch).length === 0) {
    return NextResponse.json({ error: "no changes" }, { status: 400 });
  }

  const sb = getServerClient();
  const { error } = await sb.from("feedback").update(patch).eq("id", id);
  if (error) {
    console.error("admin feedback patch:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }
  // Re-derive the admin's user_id for the audit row. We already validated
  // them as admin above; ensureUserId returns the canonical UUID.
  const adminId = await ensureUserId(u.email.toLowerCase(), null);
  await logAudit({
    userId: adminId, action: "feedback.admin_patch",
    targetKind: "feedback_id", targetId: String(id),
    payload: patch as Record<string, unknown>,
  });
  return NextResponse.json({ ok: true });
}
