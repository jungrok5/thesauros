import type { AnalysisResult } from "@/lib/types/analysis";
import { ActionBadge } from "@/components/action-badge";
import { HelpTip } from "@/components/help-tip";
import { MultiTFMatrix } from "@/components/multi-tf-matrix";
import {
  InvestorFlowChip,
  type FlowSummary,
} from "@/components/investor-flow-chip";
import {
  BookVerdict,
  isAmbushSetup,
  isPostRallyCaution,
  pickFreshBullishPattern,
} from "@/components/book-verdict";
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

      {/* 초보자 한 줄 결론 — BookVerdict 본문은 책 정신 용어 (매복/포킹/
          4등분선/catalyst 등) 가 들어가 있어 처음 보는 사람은 어려움.
          그 위에 평이한 한국어로 매수 자격 1줄. action 단독으로 결정하면
          매복/stale-pattern 분기에서 모순 ("✅ 매수 자격 가능" + "🟡 매복"
          동시) — 그래서 BookVerdict 의 분기 가드를 같이 호출해서
          downgrade. (2026-05-21) */}
      <NoviceVerdict result={r} />

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

/** NoviceVerdict — BookVerdict 위에 평이한 한국어 1줄 callout.
 *  책 정신 용어 0개. 초보자가 페이지 보고 "이 종목 사도 돼?" 답이
 *  즉시 나오게.
 *
 *  Source of truth (2026-05-22): the Python analyzer ships a fully
 *  computed `eligibility` field inside the result blob
 *  (`app/book/eligibility.py`). This component prefers that field so
 *  the page + telegram alert + push notification all show the SAME
 *  verdict text. The legacy derivation below is kept as a fallback
 *  for analyze_results rows written before the field was added (they
 *  age out within the 30-day analyze_results retention window).
 *
 *  IMPORTANT: action 단독으로 결정하면 매복/stale-pattern/post-rally
 *  분기 (BookVerdict 가 STRONG_BUY 여도 다운그레이드) 와 모순.
 *  068930.KQ 2026-05-21 reported case: action=STRONG_BUY 인데 BookVerdict
 *  는 매복 narrative — NoviceVerdict 가 "✅ 매수 자격 가능" 표시하면 모순.
 *  → BookVerdict 의 가드를 같이 호출해서 일관성 보장.
 */
function NoviceVerdict({ result }: { result: AnalysisResult }) {
  // Prefer the analyzer-computed eligibility when present — that's
  // the canonical verdict shared with the telegram alert path AND the
  // BookVerdict downgrade guard (2026-05-26: both surfaces now defer
  // to this same field so the page never shows contradictory verdicts).
  const elig = result.eligibility;
  if (elig && elig.headline) {
    const gradeColor = (
      elig.grade === "OK" ? "border-emerald-500/40 bg-emerald-500/5"
        : elig.grade === "CONDITIONAL" ? "border-amber-500/40 bg-amber-500/5"
          : elig.grade === "WATCH" ? "border-zinc-500/30 bg-zinc-500/5"
            : "border-rose-500/40 bg-rose-500/5"
    );
    return (
      <section className={`rounded-lg border-2 ${gradeColor} px-4 py-3`}>
        <div className="flex items-start gap-3">
          <span className="text-xl shrink-0">{elig.icon}</span>
          <div className="space-y-0.5">
            <div className="text-sm font-semibold">{elig.headline}</div>
            <p className="text-xs text-muted-foreground leading-relaxed">{elig.body}</p>
          </div>
        </div>
      </section>
    );
  }

  // ── Fallback derivation (pre-2026-05-22 analyze_results) ─────────
  const action = result.action;
  // BookVerdict 가 갈 분기를 미리 계산 → 같은 결정을 NoviceVerdict 도 따름.
  const bullishAction = action === "BUY" || action === "STRONG_BUY";
  const stalePattern = bullishAction
    ? (() => {
        const p = pickFreshBullishPattern(result);
        return p != null && p.runupPct > 30;
      })()
    : false;
  const postRally = bullishAction && isPostRallyCaution(result);
  const ambush = bullishAction && !stalePattern && !postRally && isAmbushSetup(result);
  const stretchHold = result.action === "HOLD" && !!result.stretch_reason;
  const reaper = (action === "SELL" || action === "SELL_OR_SHORT")
    && typeof result.stretch_reason === "string"
    && /저승사자/.test(result.stretch_reason);

  // 1) bullish action 인데 BookVerdict 가 다운그레이드하는 경우 →
  //    NoviceVerdict 도 다운그레이드.
  if (bullishAction && (ambush || stalePattern || postRally)) {
    const reason =
      ambush ? "박스권 횡보 중 (포킹 발사 대기)"
        : stalePattern ? "이미 매수 자리 한참 지남"
          : "랠리 후 조정 (반전 위험)";
    return (
      <section className="rounded-lg border-2 border-amber-500/40 bg-amber-500/5 px-4 py-3">
        <div className="flex items-start gap-3">
          <span className="text-xl shrink-0">⚠️</span>
          <div className="space-y-0.5">
            <div className="text-sm font-semibold">오늘 매수 자격: 조건부 — 지금은 자리 X</div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {reason}. 시스템이 STRONG_BUY 라벨 줬지만 실제 진입 자리는 아닙니다 —
              아래 한 줄 평 본문 참고 (책 정신상 매수 X).
            </p>
          </div>
        </div>
      </section>
    );
  }

  // 2) 일반 mapping.
  const config = {
    STRONG_BUY: {
      cls: "border-emerald-500/40 bg-emerald-500/5",
      icon: "✅",
      headline: "오늘 매수 자격: 가능 (강한 매수)",
      body: "책 정신상 매수해도 되는 자리. 단, 본인 차트 검증 후 진입 — 자동 추천 아님.",
    },
    BUY: {
      cls: "border-emerald-500/40 bg-emerald-500/5",
      icon: "✅",
      headline: "오늘 매수 자격: 가능 (매수)",
      body: "책 정신상 매수 자리. 본인 차트 + 펀더 검증 통과 시에만 진입.",
    },
    HOLD: stretchHold
      ? {
        cls: "border-amber-500/40 bg-amber-500/5",
        icon: "⚠️",
        headline: "오늘 매수 자격: 조건부 — 자리 지남",
        body: "추세는 살아있지만 신규 매수 자리는 한참 지남. 보유 중이면 유지, 신규는 X.",
      }
      : {
        cls: "border-zinc-500/30 bg-zinc-500/5",
        icon: "⏸",
        headline: "오늘 매수 자격: 관망",
        body: "보유 중이면 유지 OK, 신규 매수는 자격 X. 다음 주봉 마감까지 대기.",
      },
    AVOID: {
      cls: "border-rose-500/40 bg-rose-500/5",
      icon: "❌",
      headline: "오늘 매수 자격: 없음 (회피)",
      body: "장기 추세가 죽은 차트. 책 정신상 신규 매수 자격 X — 다른 종목 찾는 게 좋습니다.",
    },
    SELL: reaper
      ? {
        cls: "border-rose-500/40 bg-rose-500/5",
        icon: "🔴",
        headline: "오늘 매수 자격: 없음 (저승사자 — 즉시 청산)",
        body: "장대음봉이 주봉 10MA 동시 깬 상태. 보유 중이면 즉시 청산, 신규 매수 자격 0%.",
      }
      : {
        cls: "border-rose-500/40 bg-rose-500/5",
        icon: "🔴",
        headline: "오늘 매수 자격: 없음 (매도 신호)",
        body: "추세 종료 / 청산 신호. 보유 중이면 매도, 신규 매수 자격 X.",
      },
    SELL_OR_SHORT: reaper
      ? {
        cls: "border-rose-500/40 bg-rose-500/5",
        icon: "🔴",
        headline: "오늘 매수 자격: 없음 (저승사자 — 즉시 청산)",
        body: "장대음봉이 주봉 10MA 동시 깬 상태. 보유 중이면 즉시 청산, 신규 매수 자격 0%.",
      }
      : {
        cls: "border-rose-500/40 bg-rose-500/5",
        icon: "🔴",
        headline: "오늘 매수 자격: 없음 (청산 또는 인버스)",
        body: "추세 강하게 꺾임. 보유 중이면 매도 — 인버스 진입은 본인 판단.",
      },
  }[action] ?? null;

  if (!config) return null;

  return (
    <section className={`rounded-lg border-2 ${config.cls} px-4 py-3`}>
      <div className="flex items-start gap-3">
        <span className="text-xl shrink-0">{config.icon}</span>
        <div className="space-y-0.5">
          <div className="text-sm font-semibold">{config.headline}</div>
          <p className="text-xs text-muted-foreground leading-relaxed">{config.body}</p>
        </div>
      </div>
    </section>
  );
}
