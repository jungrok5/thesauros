/**
 * Watchlist — per-user list, fetched server-side by NextAuth email.
 *
 * Client-side delete via /api/watchlist (handled by `WatchlistRow`).
 */
import Link from "next/link";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { redirect } from "next/navigation";
import { WatchlistRowClient } from "./row-client";
import {
  pickFreshest,
  type FreshnessPatternInput,
} from "@/lib/freshness";
import { labelFor } from "@/lib/signal-labels";

export const dynamic = "force-dynamic";

type RawWatchlistRow = {
  id: number;
  ticker: string;
  category: "observing" | "holding";
  entry_price: number | null;
  entry_date: string | null;
  note: string | null;
  alerts_enabled: boolean;
  target_price: number | null;
  target_pct_from_entry: number | null;
  stop_price: number | null;
  stop_pct_from_entry: number | null;
  target_hit_at: string | null;
  stop_hit_at: string | null;
  created_at: string;
  tickers?: { name?: string; market?: string } | null;
};

async function fetchWatchlist(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist")
    .select(
      "id, ticker, category, entry_price, entry_date, note, alerts_enabled, " +
        "target_price, target_pct_from_entry, stop_price, stop_pct_from_entry, " +
        "target_hit_at, stop_hit_at, created_at, tickers:ticker(name, market)",
    )
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as unknown as RawWatchlistRow[];

  // Bulk-fetch latest active scan signal + analyze_results for each ticker
  // so the row can display the same freshness chip + Korean signal label
  // the recommendations / themes / closing-trade pages use. Without this,
  // a user's holding shows entry/stop/target but no answer to "is the
  // book still saying BUY this week, or has it shifted to SELL?".
  const tickers = rows.map((r) => r.ticker);
  const signalByTicker = new Map<string, { type: string; strength: number }>();
  const analyzeByTicker = new Map<
    string,
    { patterns?: FreshnessPatternInput[]; last_close?: number }
  >();
  if (tickers.length > 0) {
    const [{ data: signals }, { data: ar }] = await Promise.all([
      sb.from("scan_results")
        .select("ticker, signal_type, strength")
        .in("ticker", tickers)
        .eq("is_active", true)
        .like("signal_type", "action_%"),
      sb.from("analyze_results")
        .select("ticker, result")
        .in("ticker", tickers),
    ]);
    for (const s of signals ?? []) {
      const t = (s as { ticker: string }).ticker;
      const cur = {
        type: String((s as { signal_type: string }).signal_type),
        strength: Number((s as { strength: number }).strength),
      };
      const prev = signalByTicker.get(t);
      if (!prev || cur.strength > prev.strength) signalByTicker.set(t, cur);
    }
    for (const row of ar ?? []) {
      analyzeByTicker.set(
        (row as { ticker: string }).ticker,
        (row as { result: { patterns?: FreshnessPatternInput[]; last_close?: number } }).result,
      );
    }
  }

  return rows.map((r) => {
    const signal = signalByTicker.get(r.ticker) ?? null;
    const analyze = analyzeByTicker.get(r.ticker);
    const lastClose = analyze?.last_close ?? 0;
    const fresh = lastClose > 0 && analyze?.patterns
      ? pickFreshest(analyze.patterns, lastClose)
      : null;
    return {
      ...r,
      ticker_name: r.tickers?.name ?? null,
      ticker_market: r.tickers?.market ?? null,
      signal_label: signal ? labelFor(signal.type).label : null,
      signal_direction: signal ? labelFor(signal.type).direction : null,
      fresh: fresh ? { kind: fresh.kind, runupPct: fresh.runupPct } : null,
    };
  });
}

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  const rows = await fetchWatchlist(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  const holding = rows.filter((r) => r.category === "holding");
  const observing = rows.filter((r) => r.category === "observing");

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">관심 종목</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          주봉 종가매매 모드 — 매주 금요일 17시 KST 책 신호 자동 갱신. 보유 종목에 EXIT 신호 발생 시 텔레그램 알림.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          보유 ({holding.length})
        </h2>
        {holding.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            보유 종목이 없습니다. 종목 상세 페이지에서 &quot;보유 추가&quot; 로 등록하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {holding.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          관찰 ({observing.length})
        </h2>
        {observing.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            관찰 중인 종목이 없습니다.{" "}
            <Link href="/stocks" className="underline">종목 검색</Link>에서 추가하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {observing.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
