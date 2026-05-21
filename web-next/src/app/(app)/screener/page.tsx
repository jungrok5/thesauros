/**
 * /screener — preset-driven stock screener.
 *
 * Tone: each preset has a built-in oneLiner + action so the user
 * doesn't just see a list of tickers — they understand "이 검색이
 * 어떤 종목 찾는 거" and "발견하면 어떻게 행동할지". Matches the
 * established tone of every other interpretation card on the site.
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

export const dynamic = "force-dynamic";

interface SearchParams {
  preset?: string;
  // 매수 신호 필터 — value-classic 같은 펀더만 보는 preset 의 1위가
  // 차트 약해서 HOLD 인 케이스를 사용자가 "강매수 1위" 로 오해하는
  // 사고가 있어서, 페이지 자체에 토글 추가 (2026-05-20).
  buy_only?: string;
  // 2026-05-21 sub-score filters (universe-wide via RPC):
  vol_surge?: string;       // "1" → volume_case in (3, 9)
  zone?: string;            // "safe75" | "warn50" | "danger25" | "broken"
  catalyst_max?: string;    // "4" → catalyst_bars_since <= 4
  // 2026-05-21 secondary sort (within same book_score):
  sort2?: string;           // "vol" | "catalyst" | "zone"
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
};

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
  const { data, error } = await sb.rpc("screener_results", {
    p_per_min: f.perMin ?? null,
    p_per_max: f.perMax ?? null,
    p_pbr_max: f.pbrMax ?? null,
    p_roe_min: f.roeMin ?? null,
    p_debt_ratio_max: f.debtRatioMax ?? null,
    p_op_margin_min: f.opMarginMin ?? null,
    p_revenue_growth_min: f.revenueGrowthMin ?? null,
    p_passes_graham: f.passesGraham ?? null,
    p_passes_buffett: f.passesBuffett ?? null,
    p_passes_magic: f.passesMagicFormula ?? null,
    p_passes_kang: f.passesKangValue ?? null,
    p_action: f.action ?? null,
    p_action_in: f.actionIn ?? null,
    p_book_score_min: f.bookScoreMin ?? null,
    p_limit: 50,
    p_quarter_zone: sub.zone,
    p_volume_surge: sub.volSurge ? true : null,
    p_catalyst_max_weeks: sub.catalystMax,
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
  }));
}

/** Secondary sort within the same book_score band. Default sort within
 *  the RPC is already (book_score, action priority, ROE, ticker); this
 *  applies a stable JS re-sort to bubble the requested dimension up. */
function applySort2(hits: Hit[], sort2: string | null): Hit[] {
  if (!sort2) return hits;
  // Group by (book_score rounded to 0.01, action priority) — then sort
  // within each group by the chosen secondary key. Keeps the top-level
  // RPC ordering intact.
  const buckets = new Map<string, Hit[]>();
  const order: string[] = [];
  for (const h of hits) {
    const key = `${(h.book_score ?? 0).toFixed(2)}|${h.action ?? ""}`;
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(h);
  }
  const compare: Record<string, (a: Hit, b: Hit) => number> = {
    // 거래량 폭증 (case 3/9 우선) → 매집 (7/12) → 분배 (8/10/11) → 기타
    vol: (a, b) => volumeRank(b.volume_case_num) - volumeRank(a.volume_case_num),
    // catalyst 가장 최근 직후 우선 (null = 가장 뒤)
    catalyst: (a, b) =>
      (a.catalyst_bars_since ?? 999) - (b.catalyst_bars_since ?? 999),
    // safe75 > warn50 > 그외 > danger25/broken
    zone: (a, b) => zoneRank(b.quarter_zone) - zoneRank(a.quarter_zone),
  };
  const cmp = compare[sort2];
  if (!cmp) return hits;
  const out: Hit[] = [];
  for (const k of order) {
    const arr = buckets.get(k)!;
    arr.sort(cmp);
    out.push(...arr);
  }
  return out;
}

function volumeRank(c: number | null): number {
  if (c === 3 || c === 9) return 5;     // 매수 폭증
  if (c === 7 || c === 12) return 4;    // 매집 감소
  if (c === 0) return 3;                // 미분류
  if (c === 8 || c === 10 || c === 11) return 1;  // 분배
  return 2;
}

function zoneRank(z: string | null): number {
  if (z === "safe75") return 4;
  if (z === "warn50") return 3;
  if (z === "danger25") return 2;
  if (z === "broken") return 1;
  return 2;
}

/** Action distribution via RPC. */
async function fetchDistribution(preset: ScreenerPreset) {
  const sb = getServerClient();
  const f = preset.filter;
  const { data, error } = await sb.rpc("screener_action_distribution", {
    p_per_min: f.perMin ?? null,
    p_per_max: f.perMax ?? null,
    p_pbr_max: f.pbrMax ?? null,
    p_roe_min: f.roeMin ?? null,
    p_debt_ratio_max: f.debtRatioMax ?? null,
    p_op_margin_min: f.opMarginMin ?? null,
    p_revenue_growth_min: f.revenueGrowthMin ?? null,
    p_passes_graham: f.passesGraham ?? null,
    p_passes_buffett: f.passesBuffett ?? null,
    p_passes_magic: f.passesMagicFormula ?? null,
    p_passes_kang: f.passesKangValue ?? null,
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
  const preset = findPreset(sp.preset);
  const buyOnly = sp.buy_only === "1";
  const subFilters: SubFilters = {
    volSurge: sp.vol_surge === "1",
    zone:
      sp.zone === "safe75" || sp.zone === "warn50"
        || sp.zone === "danger25" || sp.zone === "broken"
        ? sp.zone
        : null,
    catalystMax: sp.catalyst_max ? Number(sp.catalyst_max) : null,
  };
  const sort2 =
    sp.sort2 === "vol" || sp.sort2 === "catalyst" || sp.sort2 === "zone"
      ? sp.sort2
      : null;

  // Two RPC calls in parallel — results (≤50 rows, sub-filtered) +
  // full-universe action distribution (whole-preset counts; ignores
  // sub-filters so the header is stable when user toggles them).
  const [allHits, distribution, lastAnalysisAt] = preset
    ? await Promise.all([
        runPreset(preset, subFilters),
        fetchDistribution(preset),
        fetchLatestAnalysisRun(),
      ])
    : [[], { strong_buy: 0, buy: 0, hold: 0, avoid: 0, none: 0 }, null];
  const priceMap: Map<string, LatestPrice> = allHits.length > 0
    ? await fetchLatestPrices(allHits.map((h) => h.ticker))
    : new Map();
  const totalPassing =
    distribution.strong_buy + distribution.buy + distribution.hold +
    distribution.avoid + distribution.none;
  let hits = buyOnly
    ? allHits.filter((h) => h.action === "STRONG_BUY" || h.action === "BUY")
    : allHits;
  hits = applySort2(hits, sort2);

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
          KOSPI / KOSDAQ 약 2,700 종목 중 조건에 맞는 후보 발굴.
          아래 검색 중 하나 선택하면 즉시 결과 표시. 톤 일관: 종목만 보여주는 게
          아니라 “이런 종목 발견 시 어떻게 행동할지” 함께 안내.
        </p>
      </header>

      {/* Preset 선택 — 카드 그리드 */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {PRESETS.map((p) => {
          const active = preset?.slug === p.slug;
          return (
            <Link
              key={p.slug}
              href={`/screener?preset=${p.slug}`}
              className={`rounded-lg border-2 p-4 transition-colors ${
                active
                  ? "border-foreground bg-accent"
                  : "border-border bg-card hover:bg-accent/40"
              }`}
            >
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-lg">{p.emoji}</span>
                <h2 className="text-sm font-semibold">{p.title}</h2>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {p.oneLiner}
              </p>
            </Link>
          );
        })}
      </section>

      {/* 결과 */}
      {preset && (
        <section className="space-y-3">
          <header className="rounded-xl border-2 border-foreground/20 bg-muted/30 p-4 space-y-3">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-lg">{preset.emoji}</span>
              <h2 className="text-base font-semibold">{preset.title}</h2>
              <span className="text-xs text-muted-foreground">
                · 펀더 통과 {totalPassing} 종목
              </span>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {preset.oneLiner}
            </p>
            {/* 액션 분포 — 1위가 강매수가 아닐 수 있다는 점 명시. */}
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
            <div className="rounded-md bg-background/70 border border-border p-2.5 text-xs leading-relaxed">
              <span className="font-medium">💡 발견 후 액션:</span> {preset.action}
            </div>
            {distribution.strong_buy + distribution.buy === 0
              && allHits.length > 0 && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-2.5 text-xs leading-relaxed text-rose-700 dark:text-rose-300">
                ⚠️ 이 조건 통과 종목 중 차트가 매수 자리인 종목은 <strong>0 개</strong>.
                펀더는 좋지만 차트 추세가 약함 — 책 정신상 “지금 매수” 자리 아님.
                차트가 회복될 때까지 관망하거나, 다른 검색 (예: 📚 책 정신 매수 후보)
                으로 차트 + 펀더 동시 통과 종목을 보세요.
              </div>
            )}
            {/* 정렬 + 필터 안내 */}
            <div className="flex items-baseline justify-between gap-2 flex-wrap text-[11px] text-muted-foreground">
              <span>
                <strong>정렬:</strong> 책 점수 (book_score) 높은 순 → ROE 높은 순.
                {!preset.filter.actionIn && !preset.filter.action && (
                  <> 같은 점수면 <strong>1위가 강매수가 아닐 수 있음</strong> — 차트 chip 확인 필수.</>
                )}
              </span>
              <Link
                href={`/screener?preset=${preset.slug}${buyOnly ? "" : "&buy_only=1"}`}
                className="rounded-md border border-border bg-background px-2 py-1 hover:bg-accent transition-colors"
              >
                {buyOnly ? "✓ 강매수/매수만 보는 중 (클릭=해제)" : "강매수/매수만 보기"}
              </Link>
            </div>

            {/* Sub-score 필터 + 2차 정렬 — book_score 동률 종목 안에서
                "거래량 폭증 / safe75 / catalyst 직후" 같은 진짜 매수
                자리만 골라내거나 위로 올림. (2026-05-21) */}
            <SubScoreControls
              preset={preset.slug}
              buyOnly={buyOnly}
              sub={subFilters}
              sort2={sort2}
            />

            {/* 사용자 피드백 (2026-05-21): chip 라벨 짧아서 무슨 의미인지
                모름. 한 곳에 정리해서 펼침형 details 로 노출. */}
            <details className="rounded-md border border-border bg-muted/20 px-3 py-2 text-[11px] leading-relaxed">
              <summary className="cursor-pointer font-medium text-muted-foreground select-none">
                💡 chip + 필터 의미 — 무엇을 뜻하는지 펼쳐서 보기
              </summary>
              <div className="mt-2 space-y-2.5 text-muted-foreground">
                <div>
                  <div className="font-semibold text-foreground mb-1">📊 거래량 chip (세부 column)</div>
                  <ul className="space-y-0.5 pl-2">
                    <li>· <strong>📊 바닥 폭증</strong> / <strong>급등 폭증</strong> — 거래량이 평소 대비 폭증한 양봉. 책: 세력이 들어오는 자리.</li>
                    <li>· <strong>💧 매집 감소</strong> / <strong>수렴 감소</strong> — 상승 중인데 거래량 감소. 책: 매물 소진 = 다음 발사 자리.</li>
                    <li>· <strong>🌪️ 분배 의심</strong> — 천장 폭증/세력 위임. 책: 매도 신호 — 매수 자격 X.</li>
                  </ul>
                </div>
                <div>
                  <div className="font-semibold text-foreground mb-1">🎯 4등분선 chip — 직전 장대양봉을 4등분한 매매 자리</div>
                  <ul className="space-y-0.5 pl-2">
                    <li>· <strong>🎯 safe75</strong> — 75% 위 안전지대. 책: 다음 봉 상승 확률 75%. 매수 자리.</li>
                    <li>· <strong>🎯 warn50</strong> — 50% 경계. 안전지대 살짝 벗어남. 조정 중.</li>
                    <li>· <strong>🎯 danger25</strong> — 25~50% 매입원가 영역. 적신호.</li>
                    <li>· <strong>🎯 broken</strong> — 25% 깨짐 = catalyst 부정, 매도 시그널.</li>
                  </ul>
                </div>
                <div>
                  <div className="font-semibold text-foreground mb-1">🔥 catalyst chip</div>
                  <ul className="space-y-0.5 pl-2">
                    <li>· <strong>🔥 catalyst-Nw</strong> — 장대양봉 N주 전 발생. N 작을수록 신선한 진입 자리. 8주 초과는 stale 로 표시 안 함.</li>
                  </ul>
                </div>
                <div>
                  <div className="font-semibold text-foreground mb-1">🔍 필터 (universe-wide)</div>
                  <ul className="space-y-0.5 pl-2">
                    <li>· <strong>거래량 폭증</strong> — 위 📊 바닥/급등 폭증 case 만 추림.</li>
                    <li>· <strong>safe75 / warn50</strong> — 해당 4등분선 zone 종목만.</li>
                    <li>· <strong>catalyst 4주 이내</strong> — 신선한 장대양봉 직후만.</li>
                  </ul>
                </div>
                <div>
                  <div className="font-semibold text-foreground mb-1">🔃 2차 정렬 (같은 book_score 안에서)</div>
                  <ul className="space-y-0.5 pl-2">
                    <li>· <strong>거래량</strong> — 폭증 종목을 동률 그룹 안에서 위로.</li>
                    <li>· <strong>catalyst 직후</strong> — 가장 최근 catalyst 종목 위로.</li>
                    <li>· <strong>4등분선</strong> — safe75 종목 위로.</li>
                  </ul>
                </div>
                <p className="text-[10px] pt-1 border-t border-border/50">
                  💡 이 모든 chip 은 같은 1.00 만점 종목 안에서도 &ldquo;세력 진입 + 안전지대 + 신선한 자리&rdquo; 같은
                  세부 차이를 보여주려는 용도. 책 정신: 진짜 매수 자리는 다축 모두 OK 인 곳.
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
                            href={`/stocks/${encodeURIComponent(h.ticker)}`}
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
                          <ActionPill action={h.action} score={h.book_score} />
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
                            href={`/stocks/${encodeURIComponent(h.ticker)}`}
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
                      href={`/stocks/${encodeURIComponent(h.ticker)}`}
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
      )}
    </div>
  );
}

// ActionPill moved to @/components/action-pill so /themes/[id] can use the
// same chip — keeps the two stock-list pages from drifting again.

/** Static (module-scope) chip — React 16 strict-purity rule: components
 *  cannot be created inside render. Defined once and reused by both
 *  filter and sort2 rows. */
function FilterChip({
  href,
  active,
  title,
  children,
}: {
  href: string;
  active: boolean;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      title={title}
      className={
        "rounded-full border px-2 py-0.5 transition-colors " +
        (active
          ? "border-foreground/40 bg-foreground/10 text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-muted")
      }
    >
      {children}
    </Link>
  );
}

/** Chip row for sub-score filters (universe-wide via RPC) + secondary
 *  sort (JS re-order within same book_score band). Each chip toggles a
 *  URL param so the state is shareable + bookmarkable. */
function SubScoreControls({
  preset,
  buyOnly,
  sub,
  sort2,
}: {
  preset: string;
  buyOnly: boolean;
  sub: SubFilters;
  sort2: string | null;
}) {
  function url(overrides: Record<string, string | null>): string {
    const params = new URLSearchParams();
    params.set("preset", preset);
    if (buyOnly) params.set("buy_only", "1");
    if (sub.volSurge) params.set("vol_surge", "1");
    if (sub.zone) params.set("zone", sub.zone);
    if (sub.catalystMax != null) params.set("catalyst_max", String(sub.catalystMax));
    if (sort2) params.set("sort2", sort2);
    for (const [k, v] of Object.entries(overrides)) {
      if (v == null) params.delete(k);
      else params.set(k, v);
    }
    return `/screener?${params.toString()}`;
  }

  return (
    <div className="space-y-1.5 pt-1">
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        <span className="text-muted-foreground mr-1">필터:</span>
        <FilterChip
          href={url({ vol_surge: sub.volSurge ? null : "1" })}
          active={sub.volSurge}
          title="거래량 case 3 (바닥 폭증) + case 9 (급등 양봉) 만"
        >
          📊 거래량 폭증
        </FilterChip>
        <FilterChip
          href={url({ zone: sub.zone === "safe75" ? null : "safe75" })}
          active={sub.zone === "safe75"}
          title="4등분선 75% 안전지대"
        >
          🎯 safe75
        </FilterChip>
        <FilterChip
          href={url({ zone: sub.zone === "warn50" ? null : "warn50" })}
          active={sub.zone === "warn50"}
          title="4등분선 50% 경계"
        >
          🎯 warn50
        </FilterChip>
        <FilterChip
          href={url({ catalyst_max: sub.catalystMax === 4 ? null : "4" })}
          active={sub.catalystMax === 4}
          title="장대양봉 catalyst 4주 이내 종목만"
        >
          🔥 catalyst 4주 이내
        </FilterChip>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        <span className="text-muted-foreground mr-1">2차 정렬:</span>
        <FilterChip
          href={url({ sort2: null })}
          active={!sort2}
          title="기본 정렬 — book_score → action → ROE"
        >
          기본
        </FilterChip>
        <FilterChip
          href={url({ sort2: "vol" })}
          active={sort2 === "vol"}
          title="같은 book_score 안에서 거래량 폭증 위로"
        >
          거래량
        </FilterChip>
        <FilterChip
          href={url({ sort2: "catalyst" })}
          active={sort2 === "catalyst"}
          title="같은 book_score 안에서 catalyst 최근일수록 위로"
        >
          catalyst 직후
        </FilterChip>
        <FilterChip
          href={url({ sort2: "zone" })}
          active={sort2 === "zone"}
          title="같은 book_score 안에서 4등분선 safe75 위로"
        >
          4등분선
        </FilterChip>
      </div>
    </div>
  );
}
