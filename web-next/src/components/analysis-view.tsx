import type { AnalysisResult } from "@/lib/types/analysis";
import { ActionBadge } from "@/components/action-badge";
import { HelpTip } from "@/components/help-tip";
import { MultiTFMatrix } from "@/components/multi-tf-matrix";
import {
  InvestorFlowChip,
  type FlowSummary,
} from "@/components/investor-flow-chip";
import { BookVerdict } from "@/components/book-verdict";
import { BookSummaryTable } from "@/components/book-summary-table";
import { formatNumber, cn } from "@/lib/utils";

// pattern.kind comes from the Python analyzer as Korean strings. Map them
// (partial-match) to glossary slugs so users can tap to learn what each
// pattern actually means.
const PATTERN_KEYWORD_TERM: ReadonlyArray<[RegExp, string]> = [
  [/단기.*쌍바닥/, "short_term_double_bottom"],
  [/쌍바닥/, "ssang_badak"],
  [/cup.*handle|원형\s*바닥|컵.*핸들/i, "cup_with_handle"],
  [/240\s*MA|돌반지/i, "dolbanji_240ma"],
  [/역.*헤드|inverse.*head/i, "reverse_h_and_s"],
  [/깃발|flag/i, "flag"],
  [/상승\s*삼각|ascending.*triangle/i, "ascending_triangle"],
];

function patternTerm(kind: string): string | null {
  for (const [re, term] of PATTERN_KEYWORD_TERM) {
    if (re.test(kind)) return term;
  }
  return null;
}

const TF_TERM: Record<string, string> = {
  daily: "tf_daily",
  weekly: "tf_weekly",
  monthly: "tf_monthly",
};

function PatternCard({
  p,
  lastClose,
}: {
  p: AnalysisResult["patterns"][number];
  lastClose: number;
}) {
  const dir =
    p.direction === "bullish"
      ? "text-emerald-600 dark:text-emerald-400"
      : p.direction === "bearish"
        ? "text-rose-600 dark:text-rose-400"
        : "text-amber-700 dark:text-amber-300";
  const tfBadge: Record<string, string> = {
    monthly: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
    weekly: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
    daily: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
  };
  const term = patternTerm(p.kind);

  // Freshness — `detected_at` only records the scan timestamp, and the
  // pattern's `entry` field is filled with current price for any
  // completed breakout (so `entry` always equals `lastClose`). The real
  // breakout level lives in pattern.extra (neckline / rim / ma_*).
  const ex = (p.extra ?? {}) as Record<string, unknown>;
  let breakout: number | null = null;
  for (const c of [ex.neckline, ex.rim, ex.ma_240, ex.ma_value, p.entry]) {
    if (typeof c === "number" && c > 0) { breakout = c; break; }
  }
  let runupPct: number | null = null;
  if (p.completed && breakout != null) {
    runupPct = (lastClose / breakout - 1) * 100;
  }
  const isStale = p.direction === "bullish" && runupPct != null && runupPct > 30;

  return (
    <article
      className={cn(
        "rounded-lg border bg-card p-3",
        isStale ? "border-amber-500/40 bg-amber-500/5" : "border-border",
      )}
    >
      <header className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm">
            {term ? <HelpTip term={term}>{p.kind}</HelpTip> : p.kind}
          </span>
          {p.timeframe && (
            <span
              className={cn(
                "text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded",
                tfBadge[p.timeframe] ?? tfBadge.daily,
              )}
            >
              <HelpTip term={TF_TERM[p.timeframe] ?? "tf_daily"}>
                {p.timeframe}
              </HelpTip>
            </span>
          )}
          <span className={cn("text-xs", dir)}>
            {p.direction === "bullish"
              ? "▲ 상승"
              : p.direction === "bearish"
                ? "▼ 하락"
                : "⏸ 매복"}
          </span>
          {isStale && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300 font-medium">
              ⚠ 진입 자리 지남
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground font-mono shrink-0">
          {(p.confidence * 100).toFixed(0)}%
        </span>
      </header>
      <p className="text-xs text-muted-foreground leading-relaxed">{p.reason}</p>
      {p.completed && runupPct != null && breakout != null && (
        <p className={cn(
          "mt-1.5 text-xs font-medium",
          isStale ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground",
        )}>
          돌파선 {formatNumber(breakout)} → 현재 {formatNumber(lastClose)}
          <span className="ml-1">
            ({runupPct >= 0 ? "+" : ""}{runupPct.toFixed(0)}%)
          </span>
        </p>
      )}
      <footer className="flex items-center justify-between text-[10px] text-muted-foreground/70 mt-2 pt-2 border-t border-border/60">
        <span>{p.completed ? "✓ 완성" : "⋯ 미완"}</span>
        <span>스캔 {p.detected_at?.slice(0, 10)}</span>
      </footer>
    </article>
  );
}

export function AnalysisView({
  result,
  flow,
  currentPrice,
  currentBarDate,
  analyzedAt,
}: {
  result: AnalysisResult;
  flow?: FlowSummary | null;
  /** Latest bar close from `bars` table — passed straight to
   *  <BookVerdict/> so the analysis-vs-now header chip + trigger-cleared
   *  notes can render even when analyze_results is a few days stale. */
  currentPrice?: number | null;
  currentBarDate?: string | null;
  /** `analyze_results.updated_at` (ISO) — the actual analyzer run
   *  timestamp. Used in BookVerdict's chip instead of `as_of` /
   *  `last_candle.date` which the analyzer stamps with the **next**
   *  Friday's settlement date (future). */
  analyzedAt?: string | null;
}) {
  const r = result;
  // 분석 데이터 양 — "주봉 N 개" 가 "N bars" 보다 사용자한테 직관적.
  // 분석 갱신 시각은 헷갈리는 정보 (대부분 사용자에게 무가치 + 페이지
  // 로드 시각이라 오해 소지) 라 제거. r.rows 만 남겨서 "얼마나 많은
  // 과거 데이터로 분석했는지" 만 보임.
  const barLabel = r.rows >= 60
    ? `${Math.round(r.rows / 52)}년치 주봉`
    : `${r.rows} 개 주봉`;

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight font-mono">
            {r.ticker}
          </h1>
          {/* Authoritative date + close live in <LastClose/> above this
              card (fetched fresh from Naver/Yahoo). r.as_of (next-Friday
              bar close) was hidden previously; analysis-cache timestamp
              is also hidden (it confused users who read it as "현재 시각"
              vs the actual analyze_results.updated_at). */}
          <p className="mt-1 text-sm text-muted-foreground">
            최근 {barLabel} 기준 분석
          </p>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <MultiTFMatrix
              monthly={r.trend.monthly}
              weekly={r.trend.weekly}
              daily={r.trend.daily}
            />
            {flow && <InvestorFlowChip flow={flow} />}
          </div>
        </div>
        <ActionBadge action={r.action} score={r.book_score} size="lg" />
      </header>

      <BookVerdict
        result={r}
        currentPrice={currentPrice}
        currentBarDate={currentBarDate}
        analyzedAt={analyzedAt}
      />

      {/* 책 정신 정리표 — 시간프레임/캔들/거래량/패턴/4등분선/외인을 한
          표에 집약. 이전엔 6개 카드로 흩어져 있던 정보를 사용자 매뉴얼
          분석 표 형식 그대로 노출 (Phase 2 P3 UX 정리, 2026-05-19). */}
      <BookSummaryTable result={r} flow={flow} />

      {/* 무효화되지 않은 완성 패턴이 있을 때만 detail 섹션. 한 줄로
          요약된 정보는 정리표가 이미 surface하므로, 자세히 보고싶은
          사용자만 펼침. */}
      {r.patterns.some((p) => p.completed && !p.invalidated) && (
        <details className="rounded-lg border border-border bg-card">
          <summary className="px-4 py-2.5 cursor-pointer text-xs font-semibold tracking-wider uppercase text-muted-foreground hover:text-foreground">
            감지된 패턴 자세히 ({r.patterns.filter((p) => p.completed && !p.invalidated).length}건)
          </summary>
          <div className="px-4 pb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {r.patterns
              .filter((p) => p.completed && !p.invalidated)
              .map((p, i) => (
                <PatternCard key={`${p.kind}-${p.timeframe}-${i}`} p={p} lastClose={r.last_close} />
              ))}
          </div>
        </details>
      )}

      {r.reversals.length > 0 && (
        <details className="rounded-lg border border-border bg-card">
          <summary className="px-4 py-2.5 cursor-pointer text-xs font-semibold tracking-wider uppercase text-muted-foreground hover:text-foreground">
            되돌림 패턴 자세히 ({r.reversals.length}건)
          </summary>
          <div className="px-4 pb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {r.reversals.map((p, i) => (
              <PatternCard key={`rev-${p.kind}-${i}`} p={p} lastClose={r.last_close} />
            ))}
          </div>
        </details>
      )}

      {/* 역매집 감지: 책 정신상 "심봤다" 시그널. 정리표에 한 줄 흡수
          돼있지 않으므로 별도 카드 유지. 단 발견된 경우에만 표시. */}
      {r.reverse_accumulation && (
        <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
          <div className="text-xs uppercase tracking-wider text-amber-700 dark:text-amber-300 mb-2">
            ⭐ <HelpTip term="reverse_accumulation">역매집 감지</HelpTip>
          </div>
          <p className="text-sm">{r.reverse_accumulation.reason}</p>
          <p className="text-xs text-muted-foreground mt-1">
            발생 {r.reverse_accumulation.occurrences}회 · 바닥{" "}
            {formatNumber(r.reverse_accumulation.floor)}
          </p>
        </section>
      )}

      {r.entry_plan && (() => {
        const ep = r.entry_plan;
        const last = r.last_close;
        const entryGapPct = ep.entry != null && ep.entry > 0
          ? (last / ep.entry - 1) * 100 : null;
        const stopPct = ep.entry != null && ep.entry > 0 && ep.stop != null
          ? (ep.stop / ep.entry - 1) * 100 : null;
        const targetPct = ep.entry != null && ep.entry > 0 && ep.target != null
          ? (ep.target / ep.entry - 1) * 100 : null;
        const rr = stopPct != null && targetPct != null && stopPct < 0
          ? targetPct / Math.abs(stopPct) : null;
        return (
          <section className="rounded-lg border-2 border-emerald-500/30 bg-emerald-500/5 p-5">
            <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
              <div className="text-xs uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
                💡 매매 플랜
              </div>
              {rr != null && (
                <div className="text-xs text-muted-foreground">
                  손익비 <span className="font-mono text-foreground">1:{rr.toFixed(1)}</span>
                </div>
              )}
            </div>
            <p className="text-sm text-muted-foreground mb-3">
              기준: {ep.based_on}
            </p>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <div className="text-xs text-muted-foreground mb-1">진입</div>
                <div className="text-xl font-mono">
                  {ep.entry != null ? formatNumber(ep.entry) : "—"}
                </div>
                {entryGapPct != null && Math.abs(entryGapPct) >= 1 && (
                  <div className={cn(
                    "text-[10px] mt-0.5",
                    Math.abs(entryGapPct) > 5
                      ? "text-amber-700 dark:text-amber-300"
                      : "text-muted-foreground",
                  )}>
                    현재가 대비 {entryGapPct >= 0 ? "+" : ""}{entryGapPct.toFixed(1)}%
                  </div>
                )}
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">손절</div>
                <div className="text-xl font-mono text-rose-600 dark:text-rose-400">
                  {ep.stop != null ? formatNumber(ep.stop) : "—"}
                </div>
                {stopPct != null && (
                  <div className="text-[10px] text-rose-600/80 dark:text-rose-300/80 mt-0.5">
                    {stopPct.toFixed(1)}%
                  </div>
                )}
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">목표</div>
                <div className="text-xl font-mono text-emerald-600 dark:text-emerald-400">
                  {ep.target != null ? formatNumber(ep.target) : "—"}
                </div>
                {targetPct != null && (
                  <div className="text-[10px] text-emerald-700/80 dark:text-emerald-300/80 mt-0.5">
                    +{targetPct.toFixed(0)}%
                  </div>
                )}
              </div>
            </div>
            {entryGapPct != null && entryGapPct > 5 && (
              <p className="mt-3 text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
                ⚠ 현재가가 진입가보다 {entryGapPct.toFixed(1)}% 위 — 매수 자리는 이미 지났을 수
                있습니다. 보유 평가용으로 활용 권장.
              </p>
            )}
          </section>
        );
      })()}
    </div>
  );
}
