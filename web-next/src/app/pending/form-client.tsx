"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  initialReason: string;
  alreadyPending: boolean;
}

export function PendingForm({ initialReason, alreadyPending }: Props) {
  const router = useRouter();
  const [reason, setReason] = useState(initialReason);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch("/api/access-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!r.ok) throw new Error(`${r.status}`);
      setSubmitted(true);
      router.refresh();
    } catch (e) {
      alert(`요청 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2" data-testid="pending-form">
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="예: 캔들 차트 추세추종 학습 중입니다. 관심 종목 알림 기능을 사용하고 싶습니다."
        maxLength={500}
        rows={3}
        className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
        data-testid="pending-reason"
      />
      <button
        type="submit"
        disabled={busy}
        className="w-full px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
        data-testid="pending-submit"
      >
        {busy ? "전송 중..." : alreadyPending || submitted ? "재신청" : "사용 요청 보내기"}
      </button>
    </form>
  );
}
