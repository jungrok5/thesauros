/**
 * GET    /api/admin/access-requests       — list users with status filter
 *                                            ?status=pending|approved|rejected|all
 * POST   /api/admin/access-requests       — { user_id, decision: 'approved'|'rejected', note? }
 *
 * Admin-only (the proxy enforces role='admin' for /api/admin/*).
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const VALID_STATUSES = new Set(["pending", "approved", "rejected", "all"]);
const VALID_DECISIONS = new Set(["approved", "rejected"]);
const NOTE_MAX = 500;

async function adminUserId(): Promise<string | null> {
  const session = await auth();
  if (!session?.user?.email) return null;
  const u = session.user as { role?: string };
  if (u.role !== "admin") return null;
  return await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );
}

export async function GET(req: NextRequest) {
  const adminId = await adminUserId();
  if (!adminId) {
    return NextResponse.json({ error: "admin only" }, { status: 403 });
  }
  const url = new URL(req.url);
  const status = (url.searchParams.get("status") ?? "pending").toLowerCase();
  if (!VALID_STATUSES.has(status)) {
    return NextResponse.json({ error: "invalid status" }, { status: 400 });
  }

  const sb = getServerClient();
  let q = sb
    .from("users")
    .select(
      "id, email, name, role, access_status, last_login_at, created_at, approved_at",
    )
    .order("created_at", { ascending: false })
    .limit(200);
  if (status !== "all") q = q.eq("access_status", status);
  const { data: users, error } = await q;
  if (error) {
    console.error("admin list users:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  const ids = (users ?? []).map((u) => u.id as string);
  let requestsByUser: Record<string, {
    reason: string | null;
    requested_at: string;
    decided_at: string | null;
    decision: string | null;
    note: string | null;
  }> = {};
  if (ids.length > 0) {
    const { data: reqs } = await sb
      .from("access_requests")
      .select("user_id, reason, requested_at, decided_at, decision, note")
      .in("user_id", ids);
    requestsByUser = Object.fromEntries(
      (reqs ?? []).map((r) => [r.user_id as string, r]),
    );
  }

  return NextResponse.json({
    items: (users ?? []).map((u) => ({
      ...u,
      request: requestsByUser[u.id as string] ?? null,
    })),
  });
}

export async function POST(req: NextRequest) {
  const adminId = await adminUserId();
  if (!adminId) {
    return NextResponse.json({ error: "admin only" }, { status: 403 });
  }
  const body = await req.json().catch(() => ({}));
  const userId = String(body.user_id ?? "");
  const decision = String(body.decision ?? "");
  const note = body.note ? String(body.note).slice(0, NOTE_MAX) : null;
  if (!/^[0-9a-f-]{36}$/i.test(userId) || !VALID_DECISIONS.has(decision)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }
  if (userId === adminId) {
    return NextResponse.json({ error: "cannot self-modify" }, { status: 400 });
  }

  const sb = getServerClient();
  const now = new Date().toISOString();

  // 1. flip the user's access_status (and approved_at)
  const userUpdate: Record<string, unknown> = {
    access_status: decision,
  };
  if (decision === "approved") {
    userUpdate.approved_at = now;
    userUpdate.approved_by = adminId;
  }
  const { error: uErr } = await sb
    .from("users")
    .update(userUpdate)
    .eq("id", userId);
  if (uErr) {
    console.error("admin update user:", uErr.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  // 2. upsert the access_request row so the audit trail is complete
  await sb
    .from("access_requests")
    .upsert(
      {
        user_id: userId,
        decision,
        decided_at: now,
        decided_by: adminId,
        note,
      },
      { onConflict: "user_id" },
    );

  return NextResponse.json({ ok: true });
}
