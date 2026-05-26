"use client";

/**
 * Close a paper trade. Hits POST /api/paper/[id]/close — server
 * resolves the current price + decides whether status routes to
 * closed_stop / closed_target / closed_manual.
 *
 * Phase 4: partial close (분할 매도 / 익절). Default click = full
 * close (legacy behavior). Open the dropdown to pick 25/50/75% —
 * those POST `partial_pct` and server splits the row.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

export function PaperCloseButton({ id, ticker }: { id: string; ticker: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const submit = async (partial_pct: number, label: string) => {
    if (busy) return;
    const confirmMsg = partial_pct >= 1
      ? `${ticker} 모의 투자 청산할까요? (현재 시세 기준, 전체)`
      : `${ticker} ${label} 청산할까요? (분할 매도, 남은 분 보유)`;
    if (!confirm(confirmMsg)) return;
    setBusy(true);
    setErr(null);
    setMenuOpen(false);
    try {
      const res = await fetch(`/api/paper/${id}/close`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(partial_pct >= 1 ? {} : { partial_pct }),
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
    <div className="inline-flex items-center gap-1 relative">
      {err && (
        <span className="text-xs text-rose-600 dark:text-rose-400">{err}</span>
      )}
      <button type="button" onClick={() => submit(1, "전체")} disabled={busy}
        className="text-xs px-2 py-1 rounded-l-md border border-border
                   bg-card hover:bg-muted transition-colors disabled:opacity-50">
        {busy ? "..." : "청산"}
      </button>
      <button type="button"
        onClick={() => setMenuOpen((o) => !o)}
        disabled={busy}
        title="분할 매도"
        className="text-xs px-1.5 py-1 rounded-r-md border border-l-0 border-border
                   bg-card hover:bg-muted transition-colors disabled:opacity-50">
        ▾
      </button>
      {menuOpen && (
        <div className="absolute right-0 top-full mt-1 z-10 rounded-md border
                        border-border bg-card shadow-lg min-w-[120px] py-1
                        text-xs">
          <button type="button"
            onClick={() => submit(0.25, "25%")}
            className="block w-full px-3 py-1.5 text-left hover:bg-muted">
            25% 익절
          </button>
          <button type="button"
            onClick={() => submit(0.5, "50%")}
            className="block w-full px-3 py-1.5 text-left hover:bg-muted">
            50% 익절
          </button>
          <button type="button"
            onClick={() => submit(0.75, "75%")}
            className="block w-full px-3 py-1.5 text-left hover:bg-muted">
            75% 익절
          </button>
          <button type="button"
            onClick={() => submit(1, "전체")}
            className="block w-full px-3 py-1.5 text-left hover:bg-muted
                       border-t border-border">
            전체 청산
          </button>
        </div>
      )}
    </div>
  );
}
