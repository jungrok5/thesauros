"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Row = {
  id: number;
  ticker: string;
  category: "observing" | "holding";
  entry_price: number | null;
  entry_date: string | null;
  note: string | null;
  ticker_name: string | null;
  ticker_market: string | null;
};

export function WatchlistRowClient({ row }: { row: Row }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function remove() {
    if (busy) return;
    if (!confirm(`관심 종목에서 제거하시겠습니까? ${row.ticker}`)) return;
    setBusy(true);
    try {
      const r = await fetch(
        `/api/watchlist?ticker=${encodeURIComponent(row.ticker)}`,
        { method: "DELETE" },
      );
      if (!r.ok) throw new Error(`${r.status}`);
      router.refresh();
    } catch (e) {
      alert(`제거 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3 hover:bg-muted/30">
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <Link
            href={`/stocks/${encodeURIComponent(row.ticker)}`}
            className="font-mono text-sm font-semibold hover:underline"
          >
            {row.ticker}
          </Link>
          <span className="text-sm">{row.ticker_name ?? "—"}</span>
          {row.ticker_market && (
            <span className="text-xs text-muted-foreground">
              {row.ticker_market}
            </span>
          )}
        </div>
        {row.entry_price != null && (
          <div className="mt-1 text-xs text-muted-foreground">
            진입가 {row.entry_price.toLocaleString("ko-KR")}원
            {row.entry_date && ` · ${row.entry_date}`}
          </div>
        )}
        {row.note && (
          <div className="mt-1 text-xs text-muted-foreground italic">
            {row.note}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        className="text-xs text-muted-foreground hover:text-rose-500 transition-colors disabled:opacity-50"
        aria-label="관심 종목 제거"
      >
        {busy ? "..." : "제거"}
      </button>
    </div>
  );
}
