/**
 * /admin/access — admin-only console for reviewing access requests and
 * managing existing users (approve, reject, demote/promote). The proxy
 * already enforces role=admin; this page also re-checks server-side.
 */
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { getServerClient } from "@/lib/supabase";
import { AccessRequestList } from "./list-client";

export const dynamic = "force-dynamic";

async function fetchUsers() {
  const sb = getServerClient();
  const { data: users } = await sb
    .from("users")
    .select(
      "id, email, name, role, access_status, last_login_at, created_at, approved_at",
    )
    .order("created_at", { ascending: false })
    .limit(200);
  const ids = (users ?? []).map((u) => u.id as string);
  let reqsByUser: Record<string, {
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
    reqsByUser = Object.fromEntries(
      (reqs ?? []).map((r) => [r.user_id as string, r]),
    );
  }
  return (users ?? []).map((u) => ({
    ...u,
    request: reqsByUser[u.id as string] ?? null,
  }));
}

export default async function AdminAccessPage() {
  const session = await auth();
  const u = session?.user as
    | { role?: string; email?: string }
    | undefined;
  if (!u?.email) redirect("/login");
  if (u.role !== "admin") redirect("/dashboard");

  const users = await fetchUsers();
  const pending = users.filter((x) => x.access_status === "pending");
  const approved = users.filter((x) => x.access_status === "approved");
  const rejected = users.filter((x) => x.access_status === "rejected");

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">관리자 — 접근 관리</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          사용 요청을 검토하고 승인/반려합니다. 승인한 사용자는 즉시 모든 페이지에 접근할 수 있습니다.
        </p>
      </header>

      <AccessRequestList title="대기 중" users={pending} highlight />
      <AccessRequestList title="승인됨" users={approved} />
      <AccessRequestList title="반려됨" users={rejected} />
    </div>
  );
}
