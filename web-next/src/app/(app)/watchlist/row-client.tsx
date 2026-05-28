"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { FreshnessChip } from "@/components/freshness-chip";

type Row = {
  id: number;
  ticker: string;
  category: "observing" | "holding";
  group_id: number | null;
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
  signal_label?: string | null;
  signal_direction?: "bullish" | "bearish" | "neutral" | null;
  fresh?: { kind: string; runupPct: number } | null;
  // 2026-05-28 — latest weekly close + bar date. Pair with entry_price
  // to render "등록가 → 현재가 · 수익률 %".
  current_price?: number | null;
  current_price_at?: string | null;
};

export type GroupOption = { id: number; name: string; color: string | null };

function fmt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return "";
  return String(n);
}

export function WatchlistRowClient({
  row,
  groups = [],
}: {
  row: Row;
  groups?: GroupOption[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [entry, setEntry] = useState(fmt(row.entry_price));
  const [target, setTarget] = useState(fmt(row.target_price));
  const [targetPct, setTargetPct] = useState(fmt(row.target_pct_from_entry));
  const [stop, setStop] = useState(fmt(row.stop_price));
  const [stopPct, setStopPct] = useState(fmt(row.stop_pct_from_entry));

  async function moveToGroup(newGroupId: number | null) {
    if (busy || newGroupId === row.group_id) return;
    setBusy(true);
    try {
      const r = await fetch("/api/watchlist", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: row.id, group_id: newGroupId }),
      });
      if (!r.ok) throw new Error(`${r.status}`);
      router.refresh();
    } catch (e) {
      alert(`그룹 이동 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

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
    // 책 정신 강제: 보유(holding) 종목은 손절가 / 손절 % 둘 중 하나
    // 필수. 손절 없이 사는 게 가장 큰 사고. (2026-05-26 site review.)
    if (row.category === "holding" && stop === "" && stopPct === "") {
      alert(
        "보유 종목은 손절가 또는 손절 % 입력이 필수입니다.\n\n" +
        "책 정신: 매수 전 손절가를 먼저 정한다. 손절 없이 사면 추세 깨졌을 때 빠져나오지 못함.\n\n" +
        "추천: 진입가 대비 -5% ~ -10% 사이.",
      );
      return;
    }
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
              href={`/stocks/${encodeURIComponent(row.ticker)}?from=watchlist`}
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
            {row.signal_label && (
              <span
                className={`text-xs px-1.5 py-0.5 rounded border font-medium ${
                  row.signal_direction === "bullish"
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/40"
                    : row.signal_direction === "bearish"
                      ? "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/40"
                      : "bg-muted text-muted-foreground border-border"
                }`}
                title="현재 스캔 결과의 책 신호"
              >
                {row.signal_label}
              </span>
            )}
            {row.fresh && <FreshnessChip fresh={row.fresh} compact />}
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
            {/* 2026-05-28 — 등록가 → 현재가 · 수익률. entry_price 는 종목을
                관심에 추가한 시점 (또는 첫 등록일) 의 주봉 종가 스냅샷. */}
            {row.entry_price != null && row.current_price != null && (() => {
              const ep = Number(row.entry_price);
              const cp = Number(row.current_price);
              const pct = ep > 0 ? (cp / ep - 1) * 100 : null;
              const tone = pct == null
                ? "text-muted-foreground"
                : pct > 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : pct < 0
                    ? "text-rose-600 dark:text-rose-400"
                    : "text-muted-foreground";
              return (
                <span className="font-mono">
                  등록 {ep.toLocaleString("ko-KR")}
                  {row.entry_date && (
                    <span className="text-muted-foreground/60">
                      ({row.entry_date})
                    </span>
                  )}
                  {" → "}
                  현재 {cp.toLocaleString("ko-KR")}
                  {" · "}
                  <span className={`font-semibold ${tone}`}>
                    {pct == null
                      ? "—"
                      : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`}
                  </span>
                </span>
              );
            })()}
            {/* 등록가가 없으면 (legacy row) — 알림용 메시지 */}
            {row.entry_price == null && row.current_price != null && (
              <span>
                현재 {Number(row.current_price).toLocaleString("ko-KR")}
                <span className="text-muted-foreground/60">
                  {" "}(등록가 없음 — 다시 추가하면 수익률 추적 시작)
                </span>
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
        <div className="flex items-center gap-2 flex-wrap">
          {/* 그룹 이동 dropdown — observing 종목만 그룹 분류 가능.
              holding (보유) 은 자체 "보유" 섹션이 별도라 그룹 dropdown 안 보임. */}
          {row.category === "observing" && (
            <select
              value={row.group_id ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                moveToGroup(v === "" ? null : Number(v));
              }}
              disabled={busy}
              className="text-xs px-2 py-1 rounded border border-input bg-background hover:bg-muted/30 disabled:opacity-50"
              title="그룹 이동"
            >
              <option value="">📁 미분류</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  📁 {g.name}
                </option>
              ))}
            </select>
          )}
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
        <div className="border-t border-border p-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-2">
          {row.category === "holding" && (
            <div className="col-span-2 sm:col-span-5 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-[11px] leading-relaxed">
              <div className="font-medium text-amber-700 dark:text-amber-300">
                📌 책 정신 강제: 보유 종목은 손절가 필수
              </div>
              <div className="mt-1 text-muted-foreground">
                매수 전 손절가 먼저 정함 (-5%~-10% 권장). 추가로 한 번에
                전부 매수 X — 책 정신: <strong>3~5분할 매수</strong> 권장.
                남은 분할분은 4등분선 75% 안전지대 또는 catalyst 직후
                재진입.
              </div>
            </div>
          )}
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
            <span className="text-rose-700 dark:text-rose-400">
              손절가{row.category === "holding" && (
                <span className="ml-0.5 text-rose-600" title="보유 종목 필수">*</span>
              )}
            </span>
            <input
              type="number"
              step="0.01"
              value={stop}
              onChange={(e) => setStop(e.target.value)}
              placeholder="손절가"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
              required={row.category === "holding" && stopPct === ""}
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-rose-700 dark:text-rose-400">
              손절 % (-0.05=-5%){row.category === "holding" && (
                <span className="ml-0.5 text-rose-600" title="보유 종목 필수 (또는 손절가)">*</span>
              )}
            </span>
            <input
              type="number"
              step="0.001"
              value={stopPct}
              onChange={(e) => setStopPct(e.target.value)}
              placeholder="-0.05"
              className="w-full px-2 py-1 rounded border border-input bg-background text-sm font-mono"
              required={row.category === "holding" && stop === ""}
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
