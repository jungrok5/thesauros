/**
 * /themes — Naver Finance 테마 list.
 *
 * 사용자가 테마 클릭 → /themes/[id] 에서 종목 list. 각 종목 클릭 →
 * /stocks/[ticker] 에서 책 정신 자동 분석. 사용자가 직접 검증.
 *
 * 2026-05-21 enhanced: theme_metrics() RPC 추가로 테마별 평균 1주
 * 등락률 + 상승/하락 종목 수 + 대표 종목 3개 노출. 추가 ingest 없이
 * 기존 bars + theme_members + analyze_results JOIN.
 *
 * 정렬 옵션 (URL ?sort=...):
 *   - hot (default): 평균 등락률 desc → STRONG_BUY 비율 desc
 *   - up:    평균 등락률 desc
 *   - down:  평균 등락률 asc
 *   - buys:  강매수+매수 종목 수 desc
 *   - size:  종목 수 desc
 */
import Link from "next/link";
import { ArrowLeft, Hash } from "lucide-react";
import { getServerClient } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { ThemeSortChipsClient } from "./sort-chips-client";

// theme_metrics() RPC takes 9-10 s cold (645k bars-row window sort,
// see migration 042 + EXPLAIN 2026-05-22). themes only refresh
// weekly so we let ISR cache the response for 1 h — first user
// after revalidation pays the cost, everyone else gets a hit. The
// old `dynamic = "force-dynamic"` here defeated ISR entirely and
// made every page-load pay the 9 s, often tipping over Vercel's
// 10 s function timeout and showing the "테마 데이터 없음" placeholder
// to users (the empty array fallback in fetchThemes on error).
export const revalidate = 3600; // 1 h ISR
// Bump the function ceiling from Vercel's default 10 s to 30 s so
// the cold revalidation doesn't time out either. (Hobby tier max
// is 10 s — we're on Pro per project_thesauros_deploy_state.)
export const maxDuration = 30;

type ThemeRow = {
  theme_id: number;
  name: string;
  members: number;
  avg_change_pct: number | null;
  up_count: number;
  down_count: number;
  strong_buy: number;
  buy: number;
  hold: number;
  avoid: number;
  top_tickers: string[] | null;
};

type SortKey = "hot" | "up" | "down" | "buys" | "size";

type FetchResult = { rows: ThemeRow[]; error: string | null; source: "cache" | "rpc" };

async function fetchThemes(): Promise<FetchResult> {
  const sb = getServerClient();

  // 1) Read theme_metrics_cache first (migration 046) — ~10 ms snapshot
  //    refreshed weekly by `app.db.publish_theme_metrics`. Falls back to
  //    direct RPC if cache is empty (first-run or weekly job lagging).
  const t0 = Date.now();
  const { data: cached, error: cacheErr } = await sb
    .from("theme_metrics_cache")
    .select("*");
  const cacheDur = Date.now() - t0;
  if (!cacheErr && cached && cached.length > 0) {
    return {
      rows: cached.map(normalize),
      error: null,
      source: "cache",
    };
  }
  if (cacheErr) {
    console.warn(`[themes] cache read failed after ${cacheDur}ms:`, cacheErr.message);
  } else if (cached) {
    console.info(`[themes] cache empty — falling back to RPC (weekly job may be lagging)`);
  }

  // 2) Fallback to RPC. Slow (9-10s cold) but accurate.
  const t1 = Date.now();
  const { data, error } = await sb.rpc("theme_metrics");
  const dur = Date.now() - t1;
  if (error || !data) {
    console.error(
      `[themes] theme_metrics rpc failed after ${dur}ms:`,
      error?.message,
    );
    return { rows: [], error: error?.message ?? "rpc returned no data", source: "rpc" };
  }
  if (dur > 5000) {
    console.warn(`[themes] theme_metrics rpc slow: ${dur}ms`);
  }
  type RpcRow = {
    theme_id: number;
    name: string;
    members: number;
    avg_change_pct: string | number | null;
    up_count: number;
    down_count: number;
    strong_buy: number;
    buy: number;
    hold: number;
    avoid: number;
    top_tickers: string[] | null;
  };
  const rows = (data as unknown as RpcRow[]).map(normalize);
  return { rows, error: null, source: "rpc" };
}

/** Shared normalizer for cache + RPC row shapes (they're identical). */
function normalize(r: {
  theme_id: number;
  name: string;
  members: number;
  avg_change_pct: string | number | null;
  up_count: number;
  down_count: number;
  strong_buy: number;
  buy: number;
  hold: number;
  avoid: number;
  top_tickers: string[] | null;
}): ThemeRow {
  return {
    theme_id: r.theme_id,
    name: r.name,
    members: r.members,
    avg_change_pct: r.avg_change_pct == null ? null : Number(r.avg_change_pct),
    up_count: r.up_count,
    down_count: r.down_count,
    strong_buy: r.strong_buy,
    buy: r.buy,
    hold: r.hold,
    avoid: r.avoid,
    top_tickers: r.top_tickers,
  };
}

function sortBy(rows: ThemeRow[], key: SortKey): ThemeRow[] {
  const cp = [...rows];
  if (key === "up") {
    cp.sort((a, b) => (b.avg_change_pct ?? -Infinity) - (a.avg_change_pct ?? -Infinity));
  } else if (key === "down") {
    cp.sort((a, b) => (a.avg_change_pct ?? Infinity) - (b.avg_change_pct ?? Infinity));
  } else if (key === "buys") {
    cp.sort((a, b) => (b.strong_buy * 2 + b.buy) - (a.strong_buy * 2 + a.buy));
  } else if (key === "size") {
    cp.sort((a, b) => b.members - a.members);
  } else {
    // hot: 평균 등락률 + STRONG_BUY weighting — "오르는 테마이면서 책
    // 정신상 강매수 종목이 많은 곳" 우선.
    cp.sort((a, b) => {
      const ah = (a.avg_change_pct ?? 0) + (a.strong_buy / Math.max(a.members, 1)) * 0.1;
      const bh = (b.avg_change_pct ?? 0) + (b.strong_buy / Math.max(b.members, 1)) * 0.1;
      return bh - ah;
    });
  }
  return cp;
}

// SORT_LABELS moved into sort-chips-client.tsx (single source of truth
// for chip definitions). Server uses sortKey value only.

interface PageProps {
  searchParams: Promise<{ sort?: string }>;
}

export default async function ThemesPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const sortKey: SortKey =
    (["hot", "up", "down", "buys", "size"] as SortKey[]).includes(sp.sort as SortKey)
      ? (sp.sort as SortKey)
      : "hot";
  const { rows: all, error: fetchError, source } = await fetchThemes();
  const themes = sortBy(all, sortKey);
  if (source === "rpc" && themes.length > 0) {
    // Soft warning to logs when cache miss falls through to RPC — the
    // weekly publish job (publish_theme_metrics in
    // weekly-fundamentals.yml) should keep this rare.
    console.warn("[themes] served from RPC fallback — cache empty");
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Hash className="h-6 w-6" /> 테마
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          Naver Finance 기반 한국 시장 테마 분류. 테마별 평균 등락률 + 강매수 비중.
          테마 클릭 → 종목 list. 각 종목의 책 정신 분석은 종목 페이지에서.
        </p>
      </header>

      <section className="rounded-xl border-2 border-zinc-500/30 bg-zinc-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-zinc-700 dark:text-zinc-300">
          💡 테마 활용법
        </div>
        <ul className="text-xs space-y-1 leading-relaxed text-muted-foreground">
          <li className="flex gap-2"><span>·</span><span>이 페이지는 <strong>분류만</strong> — 추천/점수 없음. 책 정신상 종목 결정은 본인 차트+펀더 검증 후.</span></li>
          <li className="flex gap-2"><span>·</span><span>예: 콜드플레이트 / AI 반도체 / 2차전지 같은 테마 찾을 때 사용.</span></li>
          <li className="flex gap-2"><span>·</span><span>테마 안의 종목 = 시장이 분류한 것. 실제 매출 비중 다양 — 본인 검증 필수.</span></li>
        </ul>
      </section>

      {/* 정렬 옵션 — client component 로 즉시 active state + isPending
          spinner (2026-05-21 — /screener PresetCardsClient 동일 패턴). */}
      <ThemeSortChipsClient />

      {themes.length === 0 ? (
        fetchError ? (
          // Distinguish "RPC failed / timed out" from "RPC returned 0
          // themes". Same blank placeholder hid both cases before, so
          // the actual debugging signal (rpc error) never reached us.
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-6 text-sm text-rose-700 dark:text-rose-300 space-y-1">
            <div className="font-medium">테마 데이터를 불러오지 못했습니다</div>
            <div className="text-xs text-rose-600/80 dark:text-rose-400/80">
              잠시 후 다시 시도해 주세요. 문제가 계속되면 관리자에게
              알려주세요. (RPC: {fetchError.slice(0, 100)})
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
            테마 데이터 없음 — weekly cron 으로 동기화 됩니다.
          </div>
        )
      ) : (
        <section>
          <div className="text-xs text-muted-foreground mb-2">
            총 <strong className="text-foreground">{themes.length}</strong> 테마
          </div>
          <ul className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {themes.map((t) => {
              const pct = t.avg_change_pct;
              const pctStr =
                pct == null
                  ? "—"
                  : `${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(1)}%`;
              const pctCls =
                pct == null
                  ? "text-muted-foreground"
                  : pct >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400";
              return (
                <li key={t.theme_id}>
                  <Link
                    href={`/themes/${t.theme_id}`}
                    className="block rounded-lg border border-border bg-card p-3 hover:bg-muted/30 transition-colors space-y-1.5"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium truncate">{t.name}</span>
                      <span className={cn("shrink-0 text-[11px] font-mono font-semibold", pctCls)}>
                        {pctStr}
                      </span>
                    </div>

                    {/* 상승/하락 종목 카운트 + 전체 종목수 */}
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                      <span>{t.members}종목</span>
                      <span className="text-emerald-600 dark:text-emerald-400">▲ {t.up_count}</span>
                      <span className="text-rose-600 dark:text-rose-400">▼ {t.down_count}</span>
                    </div>

                    {/* 대표 종목 3개 — STRONG_BUY → BUY → 나머지, book_score desc 정렬 */}
                    {t.top_tickers && t.top_tickers.length > 0 && (
                      <div className="text-[11px] text-muted-foreground truncate">
                        {t.top_tickers.join(" · ")}
                      </div>
                    )}

                    {/* 종목 action 분포 chip — 0 인 카테고리는 안 보임 */}
                    <div className="flex gap-1.5 text-[10px]">
                      {t.strong_buy > 0 && (
                        <span className="rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 px-1.5 py-0.5">
                          🟢 {t.strong_buy}
                        </span>
                      )}
                      {t.buy > 0 && (
                        <span className="rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 px-1.5 py-0.5">
                          🟡 {t.buy}
                        </span>
                      )}
                      {t.hold > 0 && (
                        <span className="rounded-full bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 px-1.5 py-0.5">
                          ⚪ {t.hold}
                        </span>
                      )}
                      {t.avoid > 0 && (
                        <span className="rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-300 px-1.5 py-0.5">
                          🔴 {t.avoid}
                        </span>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
