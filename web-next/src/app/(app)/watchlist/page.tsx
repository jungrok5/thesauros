/**
 * /watchlist — 사용자별 관심 종목.
 *
 * 두 카테고리:
 *   - 보유 (category='holding')    — 자기 own 섹션 — EXIT 알림 활성
 *   - 관심 (category='observing') — 사용자 정의 그룹별 분리 (미분류 = 그룹 없음)
 *
 * 그룹: watchlist_groups 테이블 (migration 031, 2026-05-20). 사용자 정의
 * 이름 + 색상. 종목 row 의 group_id 가 매핑. NULL group_id = 미분류 섹션.
 */
import Link from "next/link";
import { Star } from "lucide-react";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { redirect } from "next/navigation";
import { WatchlistRowClient } from "./row-client";
import { GroupManager } from "./group-manager-client";
import { groupColorClass } from "./group-colors";
import {
  pickFreshest,
  type FreshnessPatternInput,
} from "@/lib/freshness";
import { labelFor } from "@/lib/signal-labels";
import { fetchLatestPrices } from "@/lib/latest-prices";

export const dynamic = "force-dynamic";

type RawWatchlistRow = {
  id: number;
  ticker: string;
  category: "observing" | "holding";
  group_id: number | null;
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

type RawGroup = {
  id: number;
  name: string;
  color: string | null;
  order_index: number;
};

async function fetchAll(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();

  // Watchlist + groups in parallel.
  const [wlR, grR] = await Promise.all([
    sb.from("watchlist")
      .select(
        "id, ticker, category, group_id, entry_price, entry_date, note, alerts_enabled, " +
          "target_price, target_pct_from_entry, stop_price, stop_pct_from_entry, " +
          "target_hit_at, stop_hit_at, created_at, tickers:ticker(name, market)",
      )
      .eq("user_id", userId)
      .order("created_at", { ascending: false }),
    sb.from("watchlist_groups")
      .select("id, name, color, order_index")
      .eq("user_id", userId)
      .order("order_index", { ascending: true })
      .order("created_at", { ascending: true }),
  ]);

  if (wlR.error) throw new Error(wlR.error.message);
  const rows = (wlR.data ?? []) as unknown as RawWatchlistRow[];
  const groups = (grR.data ?? []) as unknown as RawGroup[];

  // Bulk-fetch signals + analyze_results (same as before).
  const tickers = rows.map((r) => r.ticker);
  const signalByTicker = new Map<string, { type: string; strength: number }>();
  const analyzeByTicker = new Map<
    string,
    { patterns?: FreshnessPatternInput[]; last_close?: number }
  >();
  if (tickers.length > 0) {
    // 2026-05-28 — explicit .limit() avoids PostgREST's silent 1000-row
    // cap (CLAUDE.md §5 함정). scan_results active rows per ticker is
    // typically 1-3 action_* signals, so 5× headroom is safe. analyze_results
    // is one row per ticker (upsert key) so == tickers.length.
    const scanLimit = Math.min(10000, tickers.length * 5);
    const arLimit = tickers.length;
    const [{ data: signals }, { data: ar }] = await Promise.all([
      sb.from("scan_results")
        .select("ticker, signal_type, strength")
        .in("ticker", tickers)
        .eq("is_active", true)
        .like("signal_type", "action_%")
        .limit(scanLimit),
      sb.from("analyze_results")
        .select("ticker, result")
        .in("ticker", tickers)
        .limit(arLimit),
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

  // 2026-05-28 — pull latest weekly close per ticker so each row can
  // show "현재가" and compute the return % vs entry_price (the
  // snapshot we take at watchlist add time). Single-batch fetch via
  // the shared latest-prices helper. Sparkline is not rendered on
  // this surface, so use skinny mode (2 bars vs 13 default).
  const priceMap = tickers.length > 0
    ? await fetchLatestPrices(tickers, { withSparkline: false })
    : new Map();

  const enriched = rows.map((r) => {
    const signal = signalByTicker.get(r.ticker) ?? null;
    const analyze = analyzeByTicker.get(r.ticker);
    const lp = priceMap.get(r.ticker);
    const currentPrice = lp?.close ?? analyze?.last_close ?? null;
    const lastClose = currentPrice ?? 0;
    const fresh = lastClose > 0 && analyze?.patterns
      ? pickFreshest(analyze.patterns, lastClose)
      : null;
    return {
      ...r,
      ticker_name: r.tickers?.name ?? null,
      ticker_market: r.tickers?.market ?? null,
      current_price: currentPrice,
      current_price_at: lp?.barDate ?? null,
      signal_label: signal ? labelFor(signal.type).label : null,
      signal_direction: signal ? labelFor(signal.type).direction : null,
      fresh: fresh ? { kind: fresh.kind, runupPct: fresh.runupPct } : null,
    };
  });

  return { rows: enriched, groups };
}

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  const { rows, groups } = await fetchAll(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  const holding = rows.filter((r) => r.category === "holding");
  const observing = rows.filter((r) => r.category === "observing");
  // 그룹별 분류 — id → rows. group_id == null 은 "미분류"
  const byGroup = new Map<number, typeof observing>();
  const unassigned: typeof observing = [];
  for (const r of observing) {
    if (r.group_id == null) {
      unassigned.push(r);
    } else {
      const arr = byGroup.get(r.group_id) ?? [];
      arr.push(r);
      byGroup.set(r.group_id, arr);
    }
  }

  // Group options for the row dropdown (id + name + color)
  const groupOptions = groups.map((g) => ({
    id: g.id,
    name: g.name,
    color: g.color,
  }));

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Star className="h-6 w-6" /> 관심 종목
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          주봉 종가매매 모드 — 매주 금요일 17 시 KST 책 신호 자동 갱신.
          보유 종목 EXIT 신호 발생 시 텔레그램 즉시 알림.
        </p>
      </header>

      <GroupManager groups={groups} />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          💼 보유 ({holding.length})
        </h2>
        {holding.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            보유 종목이 없습니다. 종목 상세 페이지에서 &quot;보유 추가&quot; 로 등록하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {holding.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} groups={groupOptions} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 그룹별 관심 종목 — 빈 그룹도 헤더는 보임 (드롭다운 매뉴를 위한 hint) */}
      {groups.map((g) => {
        const items = byGroup.get(g.id) ?? [];
        return (
          <section key={g.id} className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide flex items-center gap-2">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded border text-xs ${groupColorClass(g.color)}`}
              >
                📁 {g.name}
              </span>
              <span className="text-muted-foreground">({items.length})</span>
            </h2>
            {items.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-4 text-xs text-muted-foreground">
                비어 있음. 관심 종목 행의 그룹 dropdown 으로 이동하세요.
              </div>
            ) : (
              <ul className="space-y-2">
                {items.map((r) => (
                  <li key={r.id}>
                    <WatchlistRowClient row={r} groups={groupOptions} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {groups.length > 0 ? `📂 미분류 (${unassigned.length})` : `👀 관심 (${unassigned.length})`}
        </h2>
        {unassigned.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            {groups.length > 0
              ? "미분류 종목이 없습니다."
              : (
                <>
                  관심 종목이 없습니다.{" "}
                  <Link href="/stocks" className="underline">종목 검색</Link>에서 추가하세요.
                </>
              )}
          </div>
        ) : (
          <ul className="space-y-2">
            {unassigned.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} groups={groupOptions} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
