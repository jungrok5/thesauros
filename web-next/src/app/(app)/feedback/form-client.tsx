"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Category = "bug" | "feature" | "other";

const OPTIONS: { value: Category; label: string }[] = [
  { value: "bug", label: "🐛 버그" },
  { value: "feature", label: "💡 건의" },
  { value: "other", label: "💬 기타" },
];

export function FeedbackForm() {
  const router = useRouter();
  const [category, setCategory] = useState<Category>("bug");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !body.trim()) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category,
          title: title.trim(),
          body: body.trim(),
          // Where the user was when they decided to file the report.
          // Helps triage "the chart on /stocks/AAPL is wrong" without
          // them needing to remember the URL.
          page_url:
            typeof window !== "undefined"
              ? document.referrer || window.location.href
              : null,
        }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.error ?? `HTTP ${res.status}`);
      }
      setDone(true);
      setTitle("");
      setBody("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-4 text-sm space-y-2">
        <div className="font-medium text-emerald-700 dark:text-emerald-300">
          ✅ 접수되었습니다
        </div>
        <p className="text-xs text-muted-foreground">
          관리자에게 텔레그램 알림이 전송되었습니다. 처리 상태는 아래 목록에서
          확인할 수 있어요.
        </p>
        <button
          type="button"
          onClick={() => setDone(false)}
          className="text-xs underline hover:opacity-80"
        >
          하나 더 보내기
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => setCategory(o.value)}
            className={`px-3 py-1.5 rounded-md border-2 text-xs transition-colors ${
              category === o.value
                ? "border-foreground bg-foreground text-background"
                : "border-border bg-background hover:bg-muted"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>

      <div className="space-y-1">
        <label htmlFor="fb-title" className="text-xs text-muted-foreground">
          제목
        </label>
        <input
          id="fb-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          required
          placeholder={
            category === "bug"
              ? "예: /stocks/AAPL 차트에서 240MA가 안 보임"
              : category === "feature"
              ? "예: 관심 종목에 메모 기능 있으면 좋겠어요"
              : "한 줄로 요약"
          }
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30"
        />
      </div>

      <div className="space-y-1">
        <label htmlFor="fb-body" className="text-xs text-muted-foreground">
          내용
        </label>
        <textarea
          id="fb-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={4000}
          required
          rows={6}
          placeholder={
            category === "bug"
              ? "재현 단계, 기대 동작, 실제 동작 — 화면 캡쳐가 있으면 텔레그램으로 직접 보내주셔도 됩니다."
              : "어떤 시나리오에서 이게 도움이 될지 자세히 적어주세요."
          }
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30 font-mono leading-relaxed"
        />
        <div className="text-[10px] text-muted-foreground text-right">
          {body.length} / 4000
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-3 text-xs text-rose-700 dark:text-rose-300">
          전송 실패: {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-[11px] text-muted-foreground">
          로그인 정보가 함께 첨부됩니다. 외부에 공개되지 않습니다.
        </p>
        <button
          type="submit"
          disabled={sending || !title.trim() || !body.trim()}
          className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {sending ? "전송 중…" : "보내기"}
        </button>
      </div>
    </form>
  );
}
