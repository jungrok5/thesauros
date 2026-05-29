/**
 * /screener — book-spirit buy-candidate screener.
 *
 * 2026-05-25 site-direction reset: collapsed from 6 presets to 1.
 * The page no longer asks the user which philosophy to use — it just
 * runs the "책 정신 매수 후보" filter (actionIn=[STRONG_BUY,BUY] +
 * bookScoreMin=0.7 + roeMin=0.05) and lets the user refine via the
 * sub-score chips (volume / zone / catalyst).
 *
 * The PRESETS array + findPreset lookup are still wired through so
 * a future, book-compatible preset can be added without restructuring
 * the page. Today there's exactly one entry.
 */
import Link from "next/link";
import { ArrowLeft, ArrowRight, Filter } from "lucide-react";
import { getServerClient } from "@/lib/supabase";
import {
  PRESETS,
  findPreset,
  type ScreenerPreset,
} from "@/lib/screener-presets";
import { HelpTip } from "@/components/help-tip";
import { DataFreshness } from "@/components/data-freshness";
import { ActionPill } from "@/components/action-pill";
import { RowPrice } from "@/components/row-price";
import { fetchLatestPrices, type LatestPrice } from "@/lib/latest-prices";
import { SubScoreChips } from "@/components/sub-score-chips";
import { NextDecisionChip } from "@/components/next-decision-chip";
import { sortByBookSpirit } from "@/lib/screener-sort";
import { SubScoreControlsClient } from "./sub-score-controls-client";

/** Latest analyzer-run timestamp across analyze_results (weekly cadence). */
async function fetchLatestAnalysisRun(): Promise<string | null> {
  const sb = getServerClient();
  const { data } = await sb
    .from("analyze_results")
    .select("updated_at")
    .order("updated_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  return (data?.updated_at as string | undefined) ?? null;
}

// 2026-05-28 — analyze_results / scan_results refresh on Friday 17:30
// weekly-scan only; rest of the week the screener result is identical
// between requests. 5-minute ISR keeps the response cached and shaves
// per-render cost (RPC + 2nd .in() fetch). force-dynamic was vestigial.
export const revalidate = 300;

interface SearchParams {
  preset?: string;
  // 2026-05-21 sub-score filters (universe-wide via RPC):
  vol_surge?: string;       // "1" → volume_case in (3, 9)
  zone?: string;            // "safe75" | "warn50" | "danger25" | "broken"
  catalyst_max?: string;    // "4" → catalyst_bars_since <= 4
  // 2026-05-26 — secondary sort UI removed (sortByBookSpirit is the
  // single canonical sort). The `sort2` URL key is silently ignored
  // so old bookmarks don't 404; it just no-ops.
}

interface PageProps {
  searchParams: Promise<SearchParams>;
}

type Hit = {
  ticker: string;
  name: string | null;
  per: number | null;
  pbr: number | null;
  roe: number | null;
  debt_ratio: number | null;
  op_margin: number | null;
  // book-side signals
  action: string | null;
  book_score: number | null;
  // sub-score data (migration 043, 2026-05-21)
  volume_case_num: number | null;
  volume_label: string | null;
  volume_dir: string | null;
  quarter_zone: string | null;
  catalyst_bars_since: number | null;
  // F2 — analyzer's eligibility verdict (canonical truth). When grade
  // is not "OK", screener_results sorted-by-book_score can put an
  // unsafe ticker at rank 1 (339950.KQ case 2026-05-26: rank 1 but
  // "조건부 — 매수 X" on detail page). Chip surfaces the dissonance
  // up front so the user doesn't click through expecting a clean buy.
  eligibility_grade?: "OK" | "CONDITIONAL" | "WATCH" | "AVOID" | null;
  eligibility_icon?: string | null;
  // L2 mid-cap sweet (migration 053, 2026-05-27)
  market_cap: number | null;
  quality_score: number | null;
  safety_score: number | null;
  // Industry — for sector_cap=1 post-processing (migration 062, 2026-05-29).
  // Comes from tickers.industry (161 categories, backfilled from FDR).
  industry: string | null;
};

async function fetchEligibilityMap(
  tickers: string[],
): Promise<Map<string, { grade: string; icon: string } | null>> {
  const out = new Map<string, { grade: string; icon: string } | null>();
  if (tickers.length === 0) return out;
  const sb = getServerClient();
  // Use PostgREST's JSON-path selector so we don't pull every full
  // analyze_results.result row (each ~4-8 KB) — only the eligibility
  // subtree. .in() + .limit() avoids the silent 1000-row cap.
  const { data, error } = await sb
    .from("analyze_results")
    .select("ticker, eligibility:result->eligibility")
    .in("ticker", tickers)
    .limit(tickers.length);
  if (error || !data) {
    console.error("fetchEligibilityMap:", error?.message);
    return out;
  }
  for (const row of data as Array<{
    ticker: string;
    eligibility: { grade?: string; icon?: string } | null;
  }>) {
    const e = row.eligibility;
    if (e && typeof e.grade === "string") {
      out.set(row.ticker, { grade: e.grade, icon: e.icon ?? "" });
    } else {
      out.set(row.ticker, null);
    }
  }
  return out;
}

type SubFilters = {
  volSurge: boolean;
  zone: string | null;
  catalystMax: number | null;
};

async function runPreset(
  preset: ScreenerPreset,
  sub: SubFilters,
): Promise<Hit[]> {
  const sb = getServerClient();
  const f = preset.filter;

  // Single RPC — DB-side LEFT JOIN factors_eval × tickers × analyze_results,
  // WHERE + ORDER + LIMIT 다 처리해서 ~50 rows 만 응답. (migration 034
  // base + 043 sub-score 확장, 2026-05-21)
  //
  // The RPC schema still accepts the value-investing parameters
  // (graham/buffett/magic/kang/per/pbr/etc.) from the pre-2026-05-25
  // preset set — we just pass null for them. Kept stable so the DB
  // migration doesn't have to churn alongside frontend simplification.
  const { data, error } = await sb.rpc("screener_results", {
    p_per_min: null,
    p_per_max: null,
    p_pbr_max: null,
    p_roe_min: f.roeMin ?? null,
    p_debt_ratio_max: null,
    p_op_margin_min: null,
    p_revenue_growth_min: null,
    p_passes_graham: null,
    p_passes_buffett: null,
    p_passes_magic: null,
    p_passes_kang: null,
    p_action: null,
    p_action_in: f.actionIn ?? null,
    p_book_score_min: f.bookScoreMin ?? null,
    // p_limit=300 (not 50): RPC pre-sorts by book_score only, and ~177
    // tickers saturate at book_score=1.0 (2026-05-27). If we cap at 50
    // server-side, the true L2 winner can be dropped via the RPC's ROE
    // tiebreak before the JS L2 re-sort sees it. 300 covers the full
    // STRONG_BUY+BUY universe (~283 with book_score >= 0.7) so the JS
    // sort below picks correctly.
    p_limit: 300,
    p_quarter_zone: sub.zone,
    p_volume_surge: sub.volSurge ? true : null,
    p_catalyst_max_weeks: sub.catalystMax,
    // 2026-05-29 (migration 062): align screener with backtest's
    // DEFAULT_ENTRY_SIGNALS — only return tickers with at least one
    // active scan_results row in the top-5 entry signal set.
    p_book_entry_only: true,
  });
  if (error || !data) {
    console.error("screener_results rpc:", error?.message);
    return [];
  }
  type RpcRow = {
    ticker: string;
    name: string | null;
    per: string | number | null;
    pbr: string | number | null;
    roe: string | number | null;
    debt_ratio: string | number | null;
    op_margin: string | number | null;
    revenue_growth: string | number | null;
    action: string | null;
    book_score: string | number | null;
    volume_case_num: number | null;
    volume_label: string | null;
    volume_dir: string | null;
    quarter_zone: string | null;
    catalyst_bars_since: number | null;
    market_cap: string | number | null;
    quality_score: number | null;
    safety_score: number | null;
    industry: string | null;
  };
  const rpcRows = data as unknown as RpcRow[];
  return rpcRows.map((r) => ({
    ticker: r.ticker,
    name: r.name,
    per: numOrNull(r.per),
    pbr: numOrNull(r.pbr),
    roe: numOrNull(r.roe),
    debt_ratio: numOrNull(r.debt_ratio),
    op_margin: numOrNull(r.op_margin),
    action: r.action,
    book_score: numOrNull(r.book_score),
    volume_case_num: r.volume_case_num,
    volume_label: r.volume_label,
    volume_dir: r.volume_dir,
    quarter_zone: r.quarter_zone,
    catalyst_bars_since: r.catalyst_bars_since,
    market_cap: numOrNull(r.market_cap),
    quality_score: r.quality_score,
    safety_score: r.safety_score,
    industry: r.industry,
  }));
}


/**
 * Sector cap = 1 per industry — mirrors the backtest's
 * sector_cap_per_week=1 logic. Walks the already-sorted (by
 * sortByBookSpirit) list and keeps at most one ticker per industry.
 * Tickers with NULL/empty industry pass through (treated as their own
 * single-member bucket via the "_unknown_<ticker>" key) so the legacy
 * 4% of tickers without FDR industry data aren't all dropped.
 */
function applySectorCap<T extends { ticker: string; industry: string | null }>(
  rows: T[], capPerIndustry = 1,
): T[] {
  const counts: Record<string, number> = {};
  const out: T[] = [];
  for (const r of rows) {
    const key = (r.industry || "").trim() || `_unknown_${r.ticker}`;
    counts[key] = (counts[key] || 0);
    if (counts[key] >= capPerIndustry) continue;
    counts[key]++;
    out.push(r);
  }
  return out;
}

// sortByBookSpirit moved to @/lib/screener-sort (pure module for vitest).

/** Action distribution via RPC.
 *
 *  Same RPC-schema-stability note as runPreset — pass null for the
 *  value-investing filters that the active preset doesn't use. */
async function fetchDistribution(preset: ScreenerPreset) {
  const sb = getServerClient();
  const f = preset.filter;
  const { data, error } = await sb.rpc("screener_action_distribution", {
    p_per_min: null,
    p_per_max: null,
    p_pbr_max: null,
    p_roe_min: f.roeMin ?? null,
    p_debt_ratio_max: null,
    p_op_margin_min: null,
    p_revenue_growth_min: null,
    p_passes_graham: null,
    p_passes_buffett: null,
    p_passes_magic: null,
    p_passes_kang: null,
  });
  if (error || !data) {
    console.error("screener_action_distribution rpc:", error?.message);
    return { strong_buy: 0, buy: 0, hold: 0, avoid: 0, none: 0 };
  }
  // RPC returns a single-row TABLE; supabase-js wraps it in an array.
  const row = (Array.isArray(data) ? data[0] : data) as {
    strong_buy: number; buy: number; hold: number;
    avoid: number; unanalyzed: number;
  } | null;
  if (!row) return { strong_buy: 0, buy: 0, hold: 0, avoid: 0, none: 0 };
  return {
    strong_buy: row.strong_buy ?? 0,
    buy: row.buy ?? 0,
    hold: row.hold ?? 0,
    avoid: row.avoid ?? 0,
    none: row.unanalyzed ?? 0,
  };
}

function numOrNull(v: unknown): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtPct(v: number | null, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export default async function ScreenerPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  // Single-preset page — fall back to the default (book-buy) if the URL
  // doesn't name one (or names a removed slug from the old preset set).
  const preset = findPreset(sp.preset) ?? PRESETS[0];
  const subFilters: SubFilters = {
    volSurge: sp.vol_surge === "1",
    zone:
      sp.zone === "safe75" || sp.zone === "warn50"
        || sp.zone === "danger25" || sp.zone === "broken"
        ? sp.zone
        : null,
    catalystMax: sp.catalyst_max ? Number(sp.catalyst_max) : null,
  };

  // Two RPC calls in parallel — results (≤50 rows, sub-filtered) +
  // full-universe action distribution (whole-preset counts; ignores
  // sub-filters so the header is stable when user toggles them).
  const [allHits, distribution, lastAnalysisAt] = await Promise.all([
    runPreset(preset, subFilters),
    fetchDistribution(preset),
    fetchLatestAnalysisRun(),
  ]);
  const [priceMap, eligibilityMap] = allHits.length > 0
    ? await Promise.all([
        fetchLatestPrices(allHits.map((h) => h.ticker)),
        fetchEligibilityMap(allHits.map((h) => h.ticker)),
      ])
    : [new Map<string, LatestPrice>(), new Map<string, { grade: string; icon: string } | null>()];
  // Annotate each Hit with its eligibility verdict so chip rendering
  // is a pure UI concern (no second lookup per row).
  for (const h of allHits) {
    const e = eligibilityMap.get(h.ticker);
    if (e) {
      h.eligibility_grade = e.grade as Hit["eligibility_grade"];
      h.eligibility_icon = e.icon;
    }
  }
  const totalPassing =
    distribution.strong_buy + distribution.buy + distribution.hold +
    distribution.avoid + distribution.none;
  // preset 이 actionIn=[STRONG_BUY,BUY] 강제 → 결과 항상 매수 신호.
  // 별도 buy_only toggle 불필요 (2026-05-25 site-direction reset).
  // 책정신 정렬 (eligibility > book_score > catalyst > ROE), then
  // sector_cap=1 per industry to match the backtest production spec
  // (memory project_book_faithful_backtest). Walks the sorted list
  // and keeps at most one ticker per industry — same as the backtest's
  // sector_cap_per_week=1 logic but applied to the current snapshot.
  // RPC pre-filters to tickers with active top-5 entry signals
  // (p_book_entry_only=true), so the candidate pool == backtest's
  // candidate pool.
  const hits = applySectorCap(sortByBookSpirit(allHits)).slice(0, 50);

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Filter className="h-6 w-6" /> 종목 스크리너
          </h1>
          <DataFreshness asOf={lastAnalysisAt} cadence="weekly" label="분석" />
        </div>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          KOSPI / KOSDAQ ~2,700 종목 중 책 정신 매수 후보 — 정배열 + 240MA 위 + 적자 X.
        </p>
      </header>

      {/* "다음 결정 D-x" — 책 정신 visualize. 사용자가 매일 들여다보는
          충동을 줄이는 게 목적. 다음 매매 결정 = 다음 금요일 15:30 KST. */}
      <NextDecisionChip />

      {/* 결과 */}
      <section className="space-y-3">
          <header
            data-testid="screener-header"
            className="rounded-xl border-2 border-foreground/20 bg-muted/30 p-4 space-y-3"
          >
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-lg">{preset.emoji}</span>
              <h2 className="text-base font-semibold">{preset.title}</h2>
              <span className="text-xs text-muted-foreground">
                · 펀더 통과 {totalPassing} 종목
              </span>
            </div>

            {/* 한 줄 평 — 2026-05-29 honest (PIT look-ahead 검증 후):
                책 신호 단독 + 업종 분산 (1 종목/주/업종). 이전 L2 의
                "중형주 가산" 은 today-snapshot cap 의 look-ahead 였음이
                Phase 9 PIT 재실험으로 확인 (CAGR 20.65 → 8.07).
                Honest 17년 백테스트: CAGR +16.0% / Sharpe 0.73 / Alpha
                +7.20%/y vs KOSPI. 정렬 순서를 평문 설명 — 토글 없음. */}
            <div
              data-testid="screener-verdict"
              className="rounded-md bg-emerald-500/10 border border-emerald-500/30 p-3 text-sm leading-relaxed"
            >
              🥇 <strong>1위 = 책에 가장 부합</strong> — 책에서 가르치는
              매수 자리에 든 종목 (책 신호 점수가 가장 높은 순) 으로 정렬.
              매수 후보가 같은 업종에 몰리지 않도록 <strong>업종당 1 종목</strong>
              까지만 상위에 노출.
              <span className="block text-xs text-muted-foreground mt-1">
                17년 백테스트 결과 정직한 winner. 매수 자리 안전 등급
                (🟢 OK) → 책 신호 점수 → 신선도 → ROE 순. 조건부 / 관망 /
                회피 chip 종목은 시스템 만점이라도 진입 자리 아님.
              </span>
            </div>

            {/* 액션 분포 한 줄 */}
            <div className="flex items-center gap-2 flex-wrap text-[11px]">
              <span className="text-muted-foreground">차트 신호:</span>
              <span className="rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 px-2 py-0.5">
                🟢 강매수 {distribution.strong_buy}
              </span>
              <span className="rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 px-2 py-0.5">
                🟡 매수 {distribution.buy}
              </span>
              <span className="rounded-full bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 px-2 py-0.5">
                ⚪ 보류 {distribution.hold}
              </span>
              {distribution.avoid > 0 && (
                <span className="rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-300 px-2 py-0.5">
                  🔴 회피 {distribution.avoid}
                </span>
              )}
              {distribution.none > 0 && (
                <span className="rounded-full bg-muted text-muted-foreground px-2 py-0.5">
                  분석 대기 {distribution.none}
                </span>
              )}
            </div>

            <p className="text-xs text-muted-foreground leading-relaxed">
              💡 <strong>발견 후:</strong> {preset.action}
            </p>

            {/* 고급 필터 — default collapsed (2026-05-26 reform: 사용자
                "정렬 옵션 많고 뭐가 뭔지 모름" 피드백). 정렬은 책정신
                단일 정렬로 고정 (sortByBookSpirit), 옵션 제거. universe
                좁히고 싶을 때만 펼침. */}
            <details className="rounded-md border border-border bg-background/50 px-3 py-2 text-[11px] leading-relaxed">
              <summary className="cursor-pointer font-medium text-muted-foreground select-none hover:text-foreground">
                🔧 고급 필터 (펼치기)
              </summary>
              <div className="mt-2 space-y-2 text-muted-foreground">
                <SubScoreControlsClient preset={preset.slug} />
                <p className="pt-1 border-t border-border/50">
                  필터는 universe 좁히기용 — 거래량 폭증 / 4등분선 zone /
                  catalyst 4주 이내. 정렬은 책 부합도 단일이라 1위는 변경
                  안 됨. chip 의미: 📊 거래량 (세력 진입) · 🎯 zone (다음
                  봉 상승 확률) · 🔥 catalyst (장대양봉 N주 전).
                </p>
              </div>
            </details>
          </header>

          {hits.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
              조건 통과 종목 없음. 다른 검색을 선택하거나 기준을 완화해 보세요.
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              {/* Desktop 표 */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">종가</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        <HelpTip term="per">PER</HelpTip>
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        <HelpTip term="pbr">PBR</HelpTip>
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        <HelpTip term="roe">ROE</HelpTip>
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">부채</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">영업이익률</th>
                      <th className="px-3 py-2 text-center font-medium text-muted-foreground">매수 신호</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">세부</th>
                      <th className="px-3 py-2 text-center font-medium text-muted-foreground"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {hits.map((h, i) => (
                      <tr
                        key={h.ticker}
                        className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                      >
                        <td className="px-3 py-2">
                          <Link
                            href={`/stocks/${encodeURIComponent(h.ticker)}?from=screener${preset ? `&preset=${preset.slug}` : ""}`}
                            className="block hover:underline"
                          >
                            <div className="font-medium">{h.name ?? h.ticker}</div>
                            <div className="text-[10px] text-muted-foreground font-mono">
                              {h.ticker}
                            </div>
                          </Link>
                        </td>
                        <td className="px-3 py-2">
                          <RowPrice price={priceMap.get(h.ticker) ?? null} ticker={h.ticker} />
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {h.per?.toFixed(1) ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {h.pbr?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{fmtPct(h.roe)}</td>
                        <td className="px-3 py-2 text-right font-mono">
                          {fmtPct(h.debt_ratio, 0)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {fmtPct(h.op_margin)}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <div className="flex flex-col items-center gap-1">
                            <ActionPill action={h.action} score={h.book_score} />
                            <EligibilityChip
                              grade={h.eligibility_grade}
                              icon={h.eligibility_icon}
                            />
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <SubScoreChips
                            volumeCase={h.volume_case_num}
                            quarterZone={h.quarter_zone}
                            catalystBarsSince={h.catalyst_bars_since}
                          />
                        </td>
                        <td className="px-3 py-2 text-center">
                          <Link
                            href={`/stocks/${encodeURIComponent(h.ticker)}?from=screener${preset ? `&preset=${preset.slug}` : ""}`}
                            className="inline-flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground"
                          >
                            상세 <ArrowRight className="h-3 w-3" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile 카드 */}
              <ul className="md:hidden divide-y divide-border">
                {hits.map((h) => (
                  <li key={h.ticker} className="p-3">
                    <Link
                      href={`/stocks/${encodeURIComponent(h.ticker)}?from=screener${preset ? `&preset=${preset.slug}` : ""}`}
                      className="flex flex-col gap-2"
                    >
                      <div className="flex items-baseline justify-between gap-2 flex-wrap">
                        <div>
                          <div className="text-sm font-medium">
                            {h.name ?? h.ticker}
                          </div>
                          <div className="text-[10px] font-mono text-muted-foreground">
                            {h.ticker}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <RowPrice price={priceMap.get(h.ticker) ?? null} ticker={h.ticker} />
                          <ActionPill action={h.action} score={h.book_score} />
                          <EligibilityChip
                            grade={h.eligibility_grade}
                            icon={h.eligibility_icon}
                          />
                        </div>
                      </div>
                      <dl className="grid grid-cols-3 gap-x-2 gap-y-1 text-[11px]">
                        <div>
                          <dt className="text-muted-foreground">PER</dt>
                          <dd className="font-mono">{h.per?.toFixed(1) ?? "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">PBR</dt>
                          <dd className="font-mono">{h.pbr?.toFixed(2) ?? "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">ROE</dt>
                          <dd className="font-mono">{fmtPct(h.roe)}</dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">부채</dt>
                          <dd className="font-mono">{fmtPct(h.debt_ratio, 0)}</dd>
                        </div>
                        <div className="col-span-2">
                          <dt className="text-muted-foreground">영업이익률</dt>
                          <dd className="font-mono">{fmtPct(h.op_margin)}</dd>
                        </div>
                      </dl>
                      <SubScoreChips
                        volumeCase={h.volume_case_num}
                        quarterZone={h.quarter_zone}
                        catalystBarsSince={h.catalyst_bars_since}
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
    </div>
  );
}

/**
 * EligibilityChip — small color-coded chip next to ActionPill exposing
 * the analyzer's safety-gate verdict. F2 (2026-05-26) addressed the
 * 339950.KQ case where book_score 1.00 + STRONG_BUY put a ticker at
 * rank 1 even though `eligibility.grade` was CONDITIONAL ("월봉 240MA
 * 미계산 — 책의 핵심 안전 게이트 누락"). Sort order is preserved
 * (book_score winners stay at rank 1), but the user sees a 조건부 /
 * 관망 / 회피 chip on those rows before clicking through.
 */
function EligibilityChip({
  grade,
  icon,
}: {
  grade?: Hit["eligibility_grade"];
  icon?: string | null;
}) {
  if (!grade || grade === "OK") return null;
  const tone =
    grade === "AVOID"
      ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
      : grade === "CONDITIONAL"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
        : "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300";
  const label =
    grade === "AVOID" ? "회피"
      : grade === "CONDITIONAL" ? "조건부"
        : "관망";
  return (
    <span
      data-eligibility={grade}
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ${tone}`}
      title={
        `책 정신 적합도: ${label} — book_score 가 높아도 실제 매수 자리 ` +
        "아닐 수 있음. 상세 페이지의 한 줄 평 확인."
      }
    >
      {icon || "⚠"} {label}
    </span>
  );
}

// ActionPill moved to @/components/action-pill so other surfaces can
// reuse the same chip.
//
// SubScoreControls + FilterChip moved to sub-score-controls-client.tsx
// (client component) so chips switch instantly + show pending state
// while the new RPC result streams in. (2026-05-21)
