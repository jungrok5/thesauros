/**
 * Decompose the single `book_score` into its three sources:
 * trend (multi-TF MA stack), pattern (book's 17 patterns), volume (case 1-4).
 *
 * Without this, 12 tickers all show `score=1.00` and the user can't tell
 * which one is "trend-led" vs "pattern-led" vs "volume-led" — which is the
 * core difference that determines holding horizon and stop placement.
 */

interface Props {
  trend?: number | null;
  pattern?: number | null;
  volume?: number | null;
  compact?: boolean;
}

function bar(label: string, value: number | null | undefined) {
  const v = value == null ? 0 : Math.max(0, Math.min(1, value));
  const widthPct = (v * 100).toFixed(0);
  const tone =
    v >= 0.7
      ? "bg-emerald-500/70"
      : v >= 0.4
        ? "bg-yellow-500/70"
        : v > 0
          ? "bg-rose-500/50"
          : "bg-muted";
  return (
    <div
      key={label}
      className="flex items-center gap-1.5"
      title={`${label}: ${value == null ? "—" : value.toFixed(2)}`}
    >
      <span className="text-[10px] font-mono text-muted-foreground w-6">{label}</span>
      <div className="flex-1 h-1.5 rounded bg-muted/40 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${widthPct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground w-7 text-right">
        {value == null ? "—" : value.toFixed(2)}
      </span>
    </div>
  );
}

export function ScoreBreakdown({ trend, pattern, volume, compact = false }: Props) {
  if (compact) {
    return (
      <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
        <span title={`추세: ${trend?.toFixed(2) ?? "—"}`}>
          추 <span className="text-foreground">{trend == null ? "—" : trend.toFixed(2)}</span>
        </span>
        <span title={`패턴: ${pattern?.toFixed(2) ?? "—"}`}>
          패 <span className="text-foreground">{pattern == null ? "—" : pattern.toFixed(2)}</span>
        </span>
        <span title={`거래량: ${volume?.toFixed(2) ?? "—"}`}>
          거 <span className="text-foreground">{volume == null ? "—" : volume.toFixed(2)}</span>
        </span>
      </div>
    );
  }
  return (
    <div className="space-y-0.5 min-w-[140px]">
      {bar("추세", trend)}
      {bar("패턴", pattern)}
      {bar("거래량", volume)}
    </div>
  );
}
