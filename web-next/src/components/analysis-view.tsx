import type { AnalysisResult } from "@/lib/api";
import { ActionBadge } from "@/components/action-badge";
import { formatNumber, formatPct, cn } from "@/lib/utils";

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
          <dt className="text-muted-foreground">240MA</dt>
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
}: {
  p: AnalysisResult["patterns"][number];
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
  return (
    <article className="rounded-lg border border-border bg-card p-3">
      <header className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm">{p.kind}</span>
          {p.timeframe && (
            <span
              className={cn(
                "text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded",
                tfBadge[p.timeframe] ?? tfBadge.daily,
              )}
            >
              {p.timeframe}
            </span>
          )}
          <span className={cn("text-xs", dir)}>
            {p.direction === "bullish" ? "▲ 상승" : "▼ 하락"}
          </span>
        </div>
        <span className="text-xs text-muted-foreground font-mono shrink-0">
          {(p.confidence * 100).toFixed(0)}%
        </span>
      </header>
      <p className="text-xs text-muted-foreground leading-relaxed">{p.reason}</p>
      <footer className="flex items-center justify-between text-[10px] text-muted-foreground/70 mt-2 pt-2 border-t border-border/60">
        <span>{p.completed ? "✓ 완성" : "⋯ 미완"}</span>
        <span>{p.detected_at}</span>
      </footer>
    </article>
  );
}

export function AnalysisView({ result }: { result: AnalysisResult }) {
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
        </div>
        <ActionBadge action={r.action} score={r.book_score} size="lg" />
      </header>

      {r.trend.book_reason && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            추세 판정
          </div>
          <p className="text-sm">{r.trend.book_reason}</p>
        </div>
      )}

      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <TrendTile name="일봉" tf={r.trend.daily} />
        <TrendTile name="주봉" tf={r.trend.weekly} />
        <TrendTile name="월봉" tf={r.trend.monthly} />
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
              {r.last_candle.is_bullish ? "양봉" : "음봉"}
            </span>
            {r.last_candle.tags.map((t) => (
              <span
                key={t}
                className="text-xs px-1.5 py-0.5 rounded border border-border text-muted-foreground"
              >
                {t}
              </span>
            ))}
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
              {r.last_candle.in_safe_zone_75
                ? "✓ 4등분선 75% 안전지대 (책: 다음 봉 상승 확률 高)"
                : "⚠ 4등분선 75% 아래 — 추세 약화 가능"}
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
              <PatternCard key={`${p.kind}-${p.timeframe}-${i}`} p={p} />
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
              <PatternCard key={`rev-${p.kind}-${i}`} p={p} />
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {r.volume_case && (
          <section className="rounded-lg border border-border bg-card p-4">
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
              거래량 분류
            </div>
            <div className="font-medium text-sm mb-1">
              Case {r.volume_case.case} · {r.volume_case.label_kr}
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
              ⭐ 역매집 감지
            </div>
            <p className="text-sm">{r.reverse_accumulation.reason}</p>
            <p className="text-xs text-muted-foreground mt-1">
              발생 {r.reverse_accumulation.occurrences}회 · 바닥{" "}
              {formatNumber(r.reverse_accumulation.floor)}
            </p>
          </section>
        )}
      </div>

      {r.entry_plan && (
        <section className="rounded-lg border-2 border-emerald-500/30 bg-emerald-500/5 p-5">
          <div className="text-xs uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-3">
            💡 매매 플랜
          </div>
          <p className="text-sm text-muted-foreground mb-3">
            기준: {r.entry_plan.based_on}
          </p>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-xs text-muted-foreground mb-1">진입</div>
              <div className="text-xl font-mono">
                {formatNumber(r.entry_plan.entry)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">손절</div>
              <div className="text-xl font-mono text-rose-600 dark:text-rose-400">
                {formatNumber(r.entry_plan.stop)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">목표</div>
              <div className="text-xl font-mono text-emerald-600 dark:text-emerald-400">
                {r.entry_plan.target !== null
                  ? formatNumber(r.entry_plan.target)
                  : "—"}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
