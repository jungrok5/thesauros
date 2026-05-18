import type { AnalysisResult } from "@/lib/types/analysis";
import { ActionBadge } from "@/components/action-badge";
import { HelpTip } from "@/components/help-tip";
import { MultiTFMatrix } from "@/components/multi-tf-matrix";
import { Sparkline } from "@/components/sparkline";
import {
  InvestorFlowChip,
  type FlowSummary,
} from "@/components/investor-flow-chip";
import { BookVerdict } from "@/components/book-verdict";
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

// Candle tags emitted by the analyzer ("양봉", "장대양봉", "눈썹캔들" ...).
const CANDLE_TAG_TERM: Record<string, string> = {
  "장대양봉": "jangdae_yangbong",
  "눈썹캔들": "nunsseop_candle",
  "양봉": "yangbong",
  "음봉": "eumbong",
};

const TF_TERM: Record<string, string> = {
  daily: "tf_daily",
  weekly: "tf_weekly",
  monthly: "tf_monthly",
};

function TrendTile({
  name,
  tf,
}: {
  name: string;
  tf: AnalysisResult["trend"]["daily"];
}) {
  if (!tf) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 text-sm">
        <div className="text-muted-foreground mb-1">[{name}]</div>
        <div>데이터 부족</div>
      </div>
    );
  }
  const labelColor =
    tf.label === "강세"
      ? "text-emerald-600 dark:text-emerald-400"
      : tf.label === "약세" || tf.label === "데드"
        ? "text-rose-600 dark:text-rose-400"
        : "text-muted-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <header className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">
          [{name}]
        </span>
        <span className={cn("text-sm font-medium", labelColor)}>{tf.label}</span>
      </header>
      <div className="flex items-baseline justify-between mb-3">
        <span className="text-xs text-muted-foreground">score</span>
        <span className="font-mono text-base font-medium">
          {tf.overall_score >= 0 ? "+" : ""}
          {tf.overall_score.toFixed(2)}
        </span>
      </div>
      <dl className="space-y-1 text-xs">
        <div className="flex justify-between">
          <dt className="text-muted-foreground">price</dt>
          <dd className="font-mono">{formatNumber(tf.price)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-muted-foreground">10MA</dt>
          <dd className="font-mono">
            {formatNumber(tf.ma_10)}{" "}
            <span
              className={
                tf.above_ma_10
                  ? "text-emerald-600 dark:text-emerald-400 text-[10px]"
                  : "text-rose-600 dark:text-rose-400 text-[10px]"
              }
            >
              {tf.above_ma_10 ? "▲ 위" : "▼ 아래"}
            </span>
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-muted-foreground">
            <HelpTip term="dolbanji_240ma">240MA</HelpTip>
          </dt>
          <dd className="font-mono">
            {tf.ma_240 !== null ? formatNumber(tf.ma_240) : "—"}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-muted-foreground">정배열</dt>
          <dd className="font-mono">{tf.alignment_score.toFixed(2)}</dd>
        </div>
      </dl>
    </div>
  );
}

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
      : "text-rose-600 dark:text-rose-400";
  const tfBadge: Record<string, string> = {
    monthly: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
    weekly: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
    daily: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
  };
  const term = patternTerm(p.kind);

  // Freshness — `detected_at` only records "when the scan ran", not when
  // the formation actually completed. The real staleness signal is how
  // far price has run past the pattern's intended entry. >30% runup on
  // a completed bullish pattern = the breakout has played out.
  let runupPct: number | null = null;
  if (p.completed && p.entry && p.entry > 0) {
    runupPct = (lastClose / p.entry - 1) * 100;
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
            {p.direction === "bullish" ? "▲ 상승" : "▼ 하락"}
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
      {p.completed && runupPct != null && (
        <p className={cn(
          "mt-1.5 text-xs font-medium",
          isStale ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground",
        )}>
          진입 {formatNumber(p.entry!)} → 현재 {formatNumber(lastClose)}
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
  sparklineCloses,
}: {
  result: AnalysisResult;
  flow?: FlowSummary | null;
  sparklineCloses?: number[];
}) {
  const r = result;
  const ts = new Date().toLocaleString("ko-KR");

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight font-mono">
            {r.ticker}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            close{" "}
            <span className="font-mono text-foreground">
              {formatNumber(r.last_close)}
            </span>{" "}
            · as of {r.as_of} · {r.rows} bars · {ts}
          </p>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <MultiTFMatrix
              monthly={r.trend.monthly}
              weekly={r.trend.weekly}
              daily={r.trend.daily}
            />
            {flow && <InvestorFlowChip flow={flow} />}
            {sparklineCloses && sparklineCloses.length >= 2 && (
              <Sparkline closes={sparklineCloses} width={140} height={28} />
            )}
          </div>
        </div>
        <ActionBadge action={r.action} score={r.book_score} size="lg" />
      </header>

      <BookVerdict result={r} />

      {r.trend.book_reason && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            추세 판정
          </div>
          <p className="text-sm">{r.trend.book_reason}</p>
        </div>
      )}

      <section className={cn(
        "grid grid-cols-1 gap-3",
        // Daily tile is hidden post weekly-pivot (always null). Only show
        // when explicitly populated (legacy data or future intraday source).
        r.trend.daily ? "md:grid-cols-3" : "md:grid-cols-2",
      )}>
        <TrendTile name="월봉" tf={r.trend.monthly} />
        <TrendTile name="주봉" tf={r.trend.weekly} />
        {r.trend.daily && <TrendTile name="일봉" tf={r.trend.daily} />}
      </section>

      {r.last_candle && (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
            최근 캔들 ({r.last_candle.date})
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono">
              O {formatNumber(r.last_candle.open)} · H{" "}
              {formatNumber(r.last_candle.high)} · L{" "}
              {formatNumber(r.last_candle.low)} · C{" "}
              {formatNumber(r.last_candle.close)}
            </span>
            <span
              className={cn(
                "text-xs px-1.5 py-0.5 rounded border",
                r.last_candle.is_bullish
                  ? "border-emerald-500/40 text-emerald-700 dark:text-emerald-300"
                  : "border-rose-500/40 text-rose-700 dark:text-rose-300",
              )}
            >
              <HelpTip term={r.last_candle.is_bullish ? "yangbong" : "eumbong"}>
                {r.last_candle.is_bullish ? "양봉" : "음봉"}
              </HelpTip>
            </span>
            {r.last_candle.tags.map((t) => {
              const tagTerm = CANDLE_TAG_TERM[t];
              return (
                <span
                  key={t}
                  className="text-xs px-1.5 py-0.5 rounded border border-border text-muted-foreground"
                >
                  {tagTerm ? <HelpTip term={tagTerm}>{t}</HelpTip> : t}
                </span>
              );
            })}
          </div>
          {r.last_candle.in_safe_zone_75 !== null && (
            <p
              className={cn(
                "mt-2 text-sm",
                r.last_candle.in_safe_zone_75
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-amber-600 dark:text-amber-400",
              )}
            >
              <HelpTip term="safe_zone_75">
                {r.last_candle.in_safe_zone_75
                  ? "✓ 4등분선 75% 안전지대 — 다음 봉 상승 확률 高"
                  : "⚠ 4등분선 75% 아래 — 추세 약화 가능"}
              </HelpTip>
            </p>
          )}
        </section>
      )}

      {r.patterns.length > 0 && (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
            감지된 패턴 ({r.patterns.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {r.patterns.map((p, i) => (
              <PatternCard key={`${p.kind}-${p.timeframe}-${i}`} p={p} lastClose={r.last_close} />
            ))}
          </div>
        </section>
      )}

      {r.reversals.length > 0 && (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
            되돌림 패턴 ({r.reversals.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {r.reversals.map((p, i) => (
              <PatternCard key={`rev-${p.kind}-${i}`} p={p} lastClose={r.last_close} />
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {r.volume_case && (
          <section className="rounded-lg border border-border bg-card p-4">
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
              <HelpTip term="volume_case_generic">거래량 분류</HelpTip>
            </div>
            <div className="font-medium text-sm mb-1">
              <HelpTip
                term={
                  r.volume_case.case === 0
                    ? "volume_case_0"
                    : r.volume_case.case === 9
                      ? "volume_case_9"
                      : "volume_case_generic"
                }
              >
                Case {r.volume_case.case} · {r.volume_case.label_kr}
              </HelpTip>
            </div>
            <p className="text-xs text-muted-foreground mb-1">
              {r.volume_case.reason}
            </p>
            <span
              className={cn(
                "text-xs",
                r.volume_case.direction === "bullish"
                  ? "text-emerald-600 dark:text-emerald-400"
                  : r.volume_case.direction === "bearish"
                    ? "text-rose-600 dark:text-rose-400"
                    : "text-muted-foreground",
              )}
            >
              {r.volume_case.direction} · 신뢰도{" "}
              {(r.volume_case.confidence * 100).toFixed(0)}%
            </span>
          </section>
        )}

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
      </div>

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
