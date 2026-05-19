/**
 * Freshness chip — visualises how far price has moved past the bullish
 * pattern's breakout level. Used wherever a "is this signal still an
 * entry zone or already gone?" question matters: watchlist holdings,
 * stock-detail page, alert messages. Driven by the shared
 * `freshness()` / `bucketScore()` lib so all surfaces stay consistent.
 */

interface Props {
  /** Output of `pickFreshest()` from lib/freshness, or null when no
   *  bullish pattern with a usable breakout level was detected. */
  fresh: { kind: string; runupPct: number } | null | undefined;
  compact?: boolean;
}

export function FreshnessChip({ fresh, compact = false }: Props) {
  if (!fresh) {
    return (
      <span className="text-[10px] text-muted-foreground/60">신선도 ?</span>
    );
  }
  const r = fresh.runupPct;
  let style: string, label: string;
  if (r < -10) {
    style = "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/50";
    label = `${r.toFixed(0)}% 🔴 무효 가능`;
  } else if (r < 0) {
    style = "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/40";
    label = `${r.toFixed(0)}% 풀백`;
  } else if (r < 5) {
    style = "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/50";
    label = `+${r.toFixed(0)}% 🟢 신선`;
  } else if (r < 15) {
    style = "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30";
    label = `+${r.toFixed(0)}% 추격 가능`;
  } else if (r < 30) {
    style = "bg-yellow-500/10 text-yellow-800 dark:text-yellow-300 border-yellow-500/40";
    label = `+${r.toFixed(0)}% 일부 지남`;
  } else {
    style = "bg-amber-500/15 text-amber-800 dark:text-amber-300 border-amber-500/50";
    label = `+${r.toFixed(0)}% ⚠ 진입 자리 지남`;
  }
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium ${style}`}
      title={`${fresh.kind} 돌파선 대비 현재가 ${r >= 0 ? "+" : ""}${r.toFixed(1)}%`}
    >
      {compact ? label.split(" ").slice(0, 2).join(" ") : label}
    </span>
  );
}
