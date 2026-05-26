"use client";

/**
 * Close a paper trade. Hits POST /api/paper/[id]/close — server
 * resolves the current price + decides whether status routes to
 * closed_stop / closed_target / closed_manual.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

export function PaperCloseButton({ id, ticker }: { id: string; ticker: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const close = async () => {
    if (!confirm(`${ticker} 가짜 매수 청산할까요? (현재 시세 기준)`)) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/paper/${id}/close`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setErr(j.error ?? `청산 실패 (${res.status})`);
        return;
      }
      router.refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      {err && (
        <span className="text-xs text-rose-600 dark:text-rose-400">{err}</span>
      )}
      <button type="button" onClick={close} disabled={busy}
        className="text-xs px-2 py-1 rounded-md border border-border
                   bg-card hover:bg-muted transition-colors disabled:opacity-50">
        {busy ? "..." : "청산"}
      </button>
    </div>
  );
}
