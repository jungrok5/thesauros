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
  target_price: number | null;
  target_pct_from_entry: number | null;
  stop_price: number | null;
  stop_pct_from_entry: number | null;
  target_hit_at: string | null;
  stop_hit_at: string | null;
};

function fmt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "";
  return String(n);
}

export function WatchlistRowClient({ row }: { row: Row }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [entry, setEntry] = useState(fmt(row.entry_price));
  const [target, setTarget] = useState(fmt(row.target_price));
  const [targetPct, setTargetPct] = useState(fmt(row.target_pct_from_entry));
  const [stop, setStop] = useState(fmt(row.stop_price));
  const [stopPct, setStopPct] = useState(fmt(row.stop_pct_from_entry));

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

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        ticker: row.ticker,
        category: row.category,
        note: row.note,
      };
      if (entry !== "") body.entry_price = Number(entry);
      if (target !== "") body.target_price = Number(target);
      if (targetPct !== "") body.target_pct_from_entry = Number(targetPct);
      if (stop !== "") body.stop_price = Number(stop);
      if (stopPct !== "") body.stop_pct_from_entry = Number(stopPct);
      const r = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.error ?? String(r.status));
      }
      setOpen(false);
      router.refresh();
    } catch (e) {
      alert(`저장 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card hover:bg-muted/30 transition-colors">
      <div className="flex flex-wrap items-center gap-3 p-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
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
            {row.target_hit_at && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                🎯 목표 도달
              </span>
            )}
            {row.stop_hit_at && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-700 dark:text-rose-300">
                🛑 손절선 이탈
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            {row.entry_price != null && (
              <span>
                진입 {row.entry_price.toLocaleString("ko-KR")}
                {row.entry_date && ` · ${row.entry_date}`}
              </span>
            )}
            {row.target_price != null && (
              <span className="text-emerald-700 dark:text-emerald-400">
                목표 {row.target_price.toLocaleString("ko-KR")}
              </span>
            )}
            {row.target_pct_from_entry != null && row.target_price == null && (
              <span className="text-emerald-700 dark:text-emerald-400">
                목표 +{(Number(row.target_pct_from_entry) * 100).toFixed(1)}%
              </span>
            )}
            {row.stop_price != null && (
              <span className="text-rose-700 dark:text-rose-400">
                손절 {row.stop_price.toLocaleString("ko-KR")}
              </span>
            )}
            {row.stop_pct_from_entry != null && row.stop_price == null && (
              <span className="text-rose-700 dark:text-rose-400">
                손절 {(Number(row.stop_pct_from_entry) * 100).toFixed(1)}%
              </span>
            )}
          </div>
          {row.note && (
            <div className="mt-1 text-xs text-muted-foreground italic">
              {row.note}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            aria-expanded={open}
          >
            {open ? "닫기" : "목표·손절 ✎"}
          </button>
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
      </div>

      {open && (
        <div className="border-t border-border p-3 grid grid-cols-2 sm:grid-cols-5 gap-2">
          <label className="text-xs space-y-1">
            <span className="text-muted-foreground">진입가</span>
            <input
              type="number"
              step="0.01"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
              placeholder="진입가"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-emerald-700 dark:text-emerald-400">
              목표가
            </span>
            <input
              type="number"
              step="0.01"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="목표가"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-emerald-700 dark:text-emerald-400">
              목표 % (0.10=+10%)
            </span>
            <input
              type="number"
              step="0.001"
              value={targetPct}
              onChange={(e) => setTargetPct(e.target.value)}
              placeholder="0.10"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-rose-700 dark:text-rose-400">손절가</span>
            <input
              type="number"
              step="0.01"
              value={stop}
              onChange={(e) => setStop(e.target.value)}
              placeholder="손절가"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-rose-700 dark:text-rose-400">
              손절 % (-0.05=-5%)
            </span>
            <input
              type="number"
              step="0.001"
              value={stopPct}
              onChange={(e) => setStopPct(e.target.value)}
              placeholder="-0.05"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
            />
          </label>
          <div className="col-span-2 sm:col-span-5 flex justify-end">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="px-3 py-1.5 rounded bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "저장 중..." : "저장"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
