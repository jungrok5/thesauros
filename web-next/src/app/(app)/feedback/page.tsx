/**
 * /feedback — bug reports + feature suggestions.
 *
 * Server component renders the page chrome + the user's prior tickets;
 * the form itself is a client component (validation + submission state).
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { FeedbackForm } from "./form-client";

export const dynamic = "force-dynamic";

type Ticket = {
  id: number;
  category: string;
  title: string;
  status: string;
  created_at: string;
  admin_notes: string | null;
};

async function fetchMine(): Promise<Ticket[]> {
  const session = await auth();
  if (!session?.user?.email) return [];
  try {
    const userId = await ensureUserId(
      session.user.email.toLowerCase(),
      session.user.name ?? null,
    );
    const sb = getServerClient();
    const { data, error } = await sb
      .from("feedback")
      .select("id, category, title, status, created_at, admin_notes")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(20);
    if (error) {
      console.error("feedback list:", error.message);
      return [];
    }
    return (data ?? []) as Ticket[];
  } catch {
    return [];
  }
}

const CATEGORY_LABELS: Record<string, string> = {
  bug: "🐛 버그",
  feature: "💡 건의",
  other: "💬 기타",
};

const STATUS_LABELS: Record<string, { label: string; tone: string }> = {
  open: {
    label: "접수",
    tone: "border-sky-500/40 bg-sky-500/5 text-sky-700 dark:text-sky-300",
  },
  in_progress: {
    label: "처리 중",
    tone: "border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-300",
  },
  resolved: {
    label: "처리 완료",
    tone: "border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300",
  },
  wont_fix: {
    label: "보류",
    tone: "border-border bg-muted text-muted-foreground",
  },
};

export default async function FeedbackPage() {
  const mine = await fetchMine();

  return (
    <div className="space-y-8 max-w-3xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          🛠️ 버그 및 건의사항
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          이상한 동작을 발견했거나 새 기능 아이디어가 있으면 알려주세요. 접수
          즉시 관리자 텔레그램으로 알림이 가고, 처리 상태는 이 페이지에서 확인할
          수 있습니다.
        </p>
      </header>

      <section className="rounded-xl border border-border bg-card p-5">
        <FeedbackForm />
      </section>

      {mine.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium">내가 보낸 의견</h2>
          <ul className="divide-y divide-border rounded-lg border border-border bg-card">
            {mine.map((t) => {
              const st = STATUS_LABELS[t.status] ?? STATUS_LABELS.open;
              const cat = CATEGORY_LABELS[t.category] ?? t.category;
              return (
                <li key={t.id} className="p-4 space-y-2">
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs text-muted-foreground">{cat}</span>
                      <span className="text-sm font-medium">{t.title}</span>
                    </div>
                    <span
                      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] ${st.tone}`}
                    >
                      {st.label}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {new Date(t.created_at).toLocaleString("ko-KR")}
                  </div>
                  {t.admin_notes && (
                    <div className="rounded-md border border-border bg-muted/30 p-2 text-xs leading-relaxed">
                      <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                        관리자 코멘트
                      </div>
                      {t.admin_notes}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
