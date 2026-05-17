"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Request = {
  reason: string | null;
  requested_at: string;
  decided_at: string | null;
  decision: string | null;
  note: string | null;
};

type UserRow = {
  id: string;
  email: string;
  name: string | null;
  role: string;
  access_status: string;
  last_login_at: string | null;
  created_at: string;
  approved_at: string | null;
  request: Request | null;
};

interface Props {
  title: string;
  users: UserRow[];
  highlight?: boolean;
}

export function AccessRequestList({ title, users, highlight }: Props) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function decide(userId: string, decision: "approved" | "rejected") {
    if (busyId) return;
    const label = decision === "approved" ? "승인" : "반려";
    const note =
      decision === "rejected"
        ? prompt(`반려 사유 (선택, 사용자에게 표시됩니다):`) ?? null
        : null;
    if (!confirm(`정말 ${label}하시겠습니까?`)) return;
    setBusyId(userId);
    try {
      const r = await fetch("/api/admin/access-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, decision, note }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.error ?? String(r.status));
      }
      router.refresh();
    } catch (e) {
      alert(`${label} 실패: ${e}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      className="space-y-2"
      data-testid={`section-${title}`}
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title} ({users.length})
      </h2>
      {users.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-sm text-muted-foreground">
          없음
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {users.map((u) => (
            <li
              key={u.id}
              className={`p-3 text-sm flex flex-wrap items-start gap-3 ${
                highlight ? "bg-amber-500/5" : ""
              }`}
              data-testid={`user-row-${u.email}`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-mono text-sm font-semibold">
                    {u.email}
                  </span>
                  {u.name && (
                    <span className="text-xs text-muted-foreground">
                      {u.name}
                    </span>
                  )}
                  {u.role === "admin" && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-700 dark:text-blue-300 font-medium">
                      ADMIN
                    </span>
                  )}
                </div>
                <div
                  className="text-xs text-muted-foreground mt-0.5"
                  // Node ICU vs browser ICU disagree on `오전/AM` etc.;
                  // both renders are correct but produce different text.
                  suppressHydrationWarning
                >
                  가입: {new Date(u.created_at).toLocaleDateString("ko-KR")}
                  {u.last_login_at && (
                    <>
                      {" · 마지막 로그인: "}
                      {new Date(u.last_login_at).toLocaleString("ko-KR")}
                    </>
                  )}
                  {u.approved_at && (
                    <>
                      {" · 승인: "}
                      {new Date(u.approved_at).toLocaleDateString("ko-KR")}
                    </>
                  )}
                </div>
                {u.request?.reason && (
                  <div className="mt-1 text-xs italic text-foreground/80">
                    &quot;{u.request.reason}&quot;
                  </div>
                )}
                {u.request?.note && u.access_status === "rejected" && (
                  <div className="mt-1 text-xs text-rose-700 dark:text-rose-300">
                    반려 메모: {u.request.note}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {u.access_status !== "approved" && (
                  <button
                    type="button"
                    onClick={() => decide(u.id, "approved")}
                    disabled={busyId === u.id || u.role === "admin"}
                    className="px-3 py-1 rounded bg-emerald-600 text-white text-xs font-medium hover:opacity-90 disabled:opacity-50"
                    data-testid={`approve-${u.email}`}
                  >
                    {busyId === u.id ? "..." : "승인"}
                  </button>
                )}
                {u.access_status !== "rejected" && u.role !== "admin" && (
                  <button
                    type="button"
                    onClick={() => decide(u.id, "rejected")}
                    disabled={busyId === u.id}
                    className="px-3 py-1 rounded border border-rose-500/40 text-xs text-rose-700 dark:text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                    data-testid={`reject-${u.email}`}
                  >
                    {busyId === u.id ? "..." : "반려"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
