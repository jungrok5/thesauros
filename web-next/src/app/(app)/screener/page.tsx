/**
 * /screener — preset-driven stock screener.
 *
 * Tone: each preset has a built-in oneLiner + action so the user
 * doesn't just see a list of tickers — they understand "이 검색이
 * 어떤 종목 찾는 거" and "발견하면 어떻게 행동할지". Matches the
 * established tone of every other interpretation card on the site.
 */
import Link from "next/link";
import { ArrowLeft, ArrowRight, Search } from "lucide-react";
import { getServerClient } from "@/lib/supabase";
import {
  PRESETS,
  findPreset,
  type ScreenerPreset,
} from "@/lib/screener-presets";
import { actionDistribution } from "@/lib/screener-action-dist";

export const dynamic = "force-dynamic";

interface SearchParams {
  preset?: string;
  // 매수 신호 필터 — value-classic 같은 펀더만 보는 preset 의 1위가
  // 차트 약해서 HOLD 인 케이스를 사용자가 "강매수 1위" 로 오해하는
  // 사고가 있어서, 페이지 자체에 토글 추가 (2026-05-20).
  buy_only?: string;
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
};

async function runPreset(preset: ScreenerPreset): Promise<Hit[]> {
  const sb = getServerClient();
  const f = preset.filter;

  // Pull factors_eval first since most filters are there. Then join
  // to analyze_results for action/book_score, and to tickers for name.
  let q = sb
    .from("factors_eval")
    .select(
      "ticker, per, pbr, roe, debt_ratio, op_margin, revenue_growth, " +
        "passes_kang_value, passes_graham, passes_magic_formula, passes_buffett",
    )
    .limit(200);

  if (f.perMin != null) q = q.gte("per", f.perMin);
  if (f.perMax != null) q = q.lte("per", f.perMax).gt("per", 0);
  if (f.pbrMax != null) q = q.lte("pbr", f.pbrMax).gt("pbr", 0);
  if (f.roeMin != null) q = q.gte("roe", f.roeMin);
  if (f.debtRatioMax != null) q = q.lte("debt_ratio", f.debtRatioMax);
  if (f.opMarginMin != null) q = q.gte("op_margin", f.opMarginMin);
  if (f.revenueGrowthMin != null)
    q = q.gte("revenue_growth", f.revenueGrowthMin);
  if (f.passesBuffett != null) q = q.eq("passes_buffett", f.passesBuffett);
  if (f.passesGraham != null) q = q.eq("passes_graham", f.passesGraham);
  if (f.passesKangValue != null)
    q = q.eq("passes_kang_value", f.passesKangValue);
  if (f.passesMagicFormula != null)
    q = q.eq("passes_magic_formula", f.passesMagicFormula);

  const { data: factsRaw, error: facErr } = await q;
  if (facErr || !factsRaw) {
    console.error("screener factors_eval:", facErr?.message);
    return [];
  }
  // Supabase's generic-string-error union; cast to the row shape we
  // selected. PostgREST returns data XOR error — we already short-circuit
  // on error above.
  const facts = factsRaw as unknown as Array<{
    ticker: string;
    per: number | null;
    pbr: number | null;
    roe: number | null;
    debt_ratio: number | null;
    op_margin: number | null;
    revenue_growth: number | null;
  }>;
  const tickers = facts.map((r) => r.ticker);
  if (tickers.length === 0) return [];

  // Pull names + analyze results in parallel.
  const [namesR, anR] = await Promise.all([
    sb.from("tickers").select("ticker, name").in("ticker", tickers),
    sb.from("analyze_results").select("ticker, result").in("ticker", tickers),
  ]);
  const nameRows = (namesR.data ?? []) as unknown as Array<{
    ticker: string;
    name: string | null;
  }>;
  const anRows = (anR.data ?? []) as unknown as Array<{
    ticker: string;
    result: { action?: string; book_score?: number } | null;
  }>;
  const nameByTicker = new Map<string, string>();
  for (const r of nameRows) {
    nameByTicker.set(r.ticker, r.name ?? "");
  }
  const analyzeByTicker = new Map<string, { action?: string; score?: number }>();
  for (const r of anRows) {
    if (r.result) {
      analyzeByTicker.set(r.ticker, {
        action: r.result.action,
        score: r.result.book_score,
      });
    }
  }

  // Build hits + apply action/score filters in JS (analyze_results.result is JSONB).
  const hits: Hit[] = [];
  for (const fact of facts) {
    const an = analyzeByTicker.get(fact.ticker);
    if (f.action && an?.action !== f.action) continue;
    if (f.bookScoreMin != null && (an?.score ?? -1) < f.bookScoreMin) continue;
    hits.push({
      ticker: fact.ticker,
      name: nameByTicker.get(fact.ticker) ?? null,
      per: numOrNull(fact.per),
      pbr: numOrNull(fact.pbr),
      roe: numOrNull(fact.roe),
      debt_ratio: numOrNull(fact.debt_ratio),
      op_margin: numOrNull(fact.op_margin),
      action: an?.action ?? null,
      book_score: an?.score ?? null,
    });
  }
  // Sort: book_score desc → roe desc → ticker
  hits.sort((a, b) => {
    const s = (b.book_score ?? 0) - (a.book_score ?? 0);
    if (s !== 0) return s;
    return (b.roe ?? -1) - (a.roe ?? -1);
  });
  return hits.slice(0, 50);
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
  const allHits = preset ? await runPreset(preset) : [];
  // Distribution counts ALL action variants including SELL_OR_SHORT —
  // the helper locks this in via test (see screener-action-dist.test.ts).
  const distribution = actionDistribution(allHits);
  const hits = buyOnly
    ? allHits.filter((h) => h.action === "STRONG_BUY" || h.action === "BUY")
    : allHits;

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
          <Search className="h-6 w-6" /> 종목 스크리너
        </h1>
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
                · 펀더 통과 {allHits.length} 종목
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
                정렬: 책 점수 (book_score) 높은 순 — <strong>1위 ≠ 강매수</strong> 일 수
                있음. 차트 신호 chip 확인 필수.
              </span>
              <Link
                href={`/screener?preset=${preset.slug}${buyOnly ? "" : "&buy_only=1"}`}
                className="rounded-md border border-border bg-background px-2 py-1 hover:bg-accent transition-colors"
              >
                {buyOnly ? "✓ 강매수/매수만 보는 중 (클릭=해제)" : "강매수/매수만 보기"}
              </Link>
            </div>
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
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">PER</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">PBR</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">ROE</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">부채</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">영업이익률</th>
                      <th className="px-3 py-2 text-center font-medium text-muted-foreground">매수 신호</th>
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
                        <ActionPill action={h.action} score={h.book_score} />
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

function ActionPill({
  action,
  score,
}: {
  action: string | null;
  score: number | null;
}) {
  if (!action) {
    return (
      <span className="inline-flex items-center rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px]">
        대기
      </span>
    );
  }
  const isAvoid =
    action === "AVOID" || action === "SELL" || action === "SELL_OR_SHORT";
  const tone =
    action === "STRONG_BUY"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
      : action === "BUY"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
        : isAvoid
          ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
          : "bg-muted text-muted-foreground";
  const label: Record<string, string> = {
    STRONG_BUY: "🟢 강매수",
    BUY: "🟡 매수",
    HOLD: "⚪ 보류",
    AVOID: "🔴 회피",
    SELL: "🔴 청산",
    SELL_OR_SHORT: "🔴 매도/숏",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] ${tone}`}
    >
      {label[action] ?? action}
      {score != null && ` · ${(score * 10).toFixed(1)}/10`}
    </span>
  );
}
