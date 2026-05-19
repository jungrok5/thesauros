"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

type Row = {
  id: number;
  user_email: string | null;
  category: string;
  title: string;
  body: string;
  status: string;
  admin_notes: string | null;
  page_url: string | null;
  user_agent: string | null;
  created_at: string;
};

const STATUS_OPTIONS = [
  { value: "open", label: "접수" },
  { value: "in_progress", label: "처리 중" },
  { value: "resolved", label: "완료" },
  { value: "wont_fix", label: "보류" },
];

const CATEGORY_LABEL: Record<string, string> = {
  bug: "🐛 버그",
  feature: "💡 건의",
  other: "💬 기타",
};

export function FeedbackRow({ row }: { row: Row }) {
  const router = useRouter();
  const [status, setStatus] = useState(row.status);
  const [notes, setNotes] = useState(row.admin_notes ?? "");
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  async function save(patch: { status?: string; admin_notes?: string }) {
    setError(null);
    start(async () => {
      try {
        const res = await fetch(`/api/admin/feedback/${row.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        if (!res.ok) {
          const j = await res.json().catch(() => ({}));
          throw new Error(j.error ?? `HTTP ${res.status}`);
        }
        router.refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    });
  }

  return (
    <article className="p-4 space-y-3">
      <header className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-xs text-muted-foreground">
            #{row.id} · {CATEGORY_LABEL[row.category] ?? row.category}
          </span>
          <span className="text-sm font-medium">{row.title}</span>
        </div>
        <div className="text-[10px] text-muted-foreground">
          {new Date(row.created_at).toLocaleString("ko-KR")}
        </div>
      </header>

      <div className="text-xs text-muted-foreground">
        {row.user_email ?? "(unknown user)"}
        {row.page_url && (
          <>
            {" · "}
            <a
              href={row.page_url}
              target="_blank"
              rel="noopener"
              className="underline hover:text-foreground"
            >
              {row.page_url}
            </a>
          </>
        )}
      </div>

      <pre className="whitespace-pre-wrap text-xs leading-relaxed font-mono rounded-md border border-border bg-muted/30 p-3 max-h-64 overflow-auto">
        {row.body}
      </pre>

      {row.user_agent && (
        <div className="text-[10px] text-muted-foreground truncate">
          UA: {row.user_agent}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={status}
          onChange={(e) => {
            const next = e.target.value;
            setStatus(next);
            void save({ status: next });
          }}
          disabled={pending}
          className="rounded-md border border-input bg-background px-2 py-1 text-xs"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {pending && (
          <span className="text-[11px] text-muted-foreground">저장 중…</span>
        )}
        {error && (
          <span className="text-[11px] text-rose-600 dark:text-rose-400">
            {error}
          </span>
        )}
      </div>

      <div className="space-y-1">
        <label className="text-[11px] text-muted-foreground">
          관리자 코멘트 (사용자에게 보임)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => {
            if (notes !== (row.admin_notes ?? "")) {
              void save({ admin_notes: notes });
            }
          }}
          rows={2}
          maxLength={2000}
          placeholder="비워두면 사용자에게 표시 안 됨."
          className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs"
        />
      </div>
    </article>
  );
}
