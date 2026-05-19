/**
 * /admin/feedback — triage list for bug + feature submissions.
 *
 * Status transitions: open → in_progress → resolved | wont_fix. The
 * "open" bucket is the always-on top; resolved ones fold under a
 * <details> so the page stays focused on what still needs attention.
 */
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { getServerClient } from "@/lib/supabase";
import { FeedbackRow } from "./row-client";

export const dynamic = "force-dynamic";

type Row = {
  id: number;
  user_id: string | null;
  user_email: string | null;
  category: string;
  title: string;
  body: string;
  status: string;
  admin_notes: string | null;
  page_url: string | null;
  user_agent: string | null;
  created_at: string;
  updated_at: string;
};

async function fetchAll(): Promise<Row[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("feedback")
    .select(
      "id, user_id, user_email, category, title, body, status, admin_notes, page_url, user_agent, created_at, updated_at",
    )
    .order("created_at", { ascending: false })
    .limit(500);
  if (error) {
    console.error("admin feedback fetch:", error.message);
    return [];
  }
  return (data ?? []) as Row[];
}

export default async function AdminFeedbackPage() {
  const session = await auth();
  const u = session?.user as { role?: string; email?: string } | undefined;
  if (!u?.email) redirect("/login");
  if (u.role !== "admin") redirect("/dashboard");

  const all = await fetchAll();
  const open = all.filter((r) => r.status === "open");
  const inProgress = all.filter((r) => r.status === "in_progress");
  const closed = all.filter(
    (r) => r.status === "resolved" || r.status === "wont_fix",
  );

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          관리자 — 버그·건의
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          사용자 제보를 검토하고 처리 상태를 갱신합니다. 새 접수는 텔레그램으로도
          알림이 옵니다.
        </p>
      </header>

      <Bucket title="🆕 접수" rows={open} initiallyOpen />
      <Bucket title="🛠️ 처리 중" rows={inProgress} initiallyOpen />
      <Bucket title="📦 처리 완료 · 보류" rows={closed} />
    </div>
  );
}

function Bucket({
  title,
  rows,
  initiallyOpen = false,
}: {
  title: string;
  rows: Row[];
  initiallyOpen?: boolean;
}) {
  if (rows.length === 0) {
    return (
      <details open={initiallyOpen} className="rounded-lg border border-border bg-card">
        <summary className="px-4 py-3 cursor-pointer text-sm font-semibold tracking-tight hover:bg-muted/40">
          {title} <span className="text-xs text-muted-foreground">(0)</span>
        </summary>
        <div className="px-4 pb-4 text-sm text-muted-foreground">없음.</div>
      </details>
    );
  }
  return (
    <details open={initiallyOpen} className="rounded-lg border border-border bg-card">
      <summary className="px-4 py-3 cursor-pointer text-sm font-semibold tracking-tight hover:bg-muted/40">
        {title}{" "}
        <span className="text-xs text-muted-foreground">({rows.length})</span>
      </summary>
      <ul className="divide-y divide-border border-t border-border">
        {rows.map((r) => (
          <li key={r.id}>
            <FeedbackRow row={r} />
          </li>
        ))}
      </ul>
    </details>
  );
}
