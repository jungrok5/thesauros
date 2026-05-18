/**
 * Top patterns as 1st-class chips on the recommendations row.
 *
 * Book's value lives in "what specific pattern fired" (정배열, 4등분선 25%,
 * 매물대 돌파, etc.) — not in a single STRONG_BUY label. Surface up to 3
 * top patterns with timeframe tag so the user can scan a list of 50 and
 * actually see why each one ranked.
 */
import { HelpTip } from "@/components/help-tip";

export interface PatternBlock {
  kind: string;
  direction: "bullish" | "bearish" | "neutral";
  confidence: number;
  timeframe?: string;       // "daily" | "weekly" | "monthly"
  completed?: boolean;
}

const TF_BADGE: Record<string, string> = {
  monthly: "월",
  weekly: "주",
  daily: "일",
};

function chipColor(direction: PatternBlock["direction"]): string {
  if (direction === "bullish") {
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30";
  }
  if (direction === "bearish") {
    return "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/30";
  }
  return "bg-muted text-muted-foreground border-border";
}

interface Props {
  patterns: PatternBlock[];
  max?: number;
}

export function PatternChips({ patterns, max = 3 }: Props) {
  if (!patterns?.length) {
    return (
      <span className="text-[10px] text-muted-foreground italic">
        패턴 없음
      </span>
    );
  }
  // Pick the strongest few: prefer completed bullish, sort by (monthly>weekly>daily, confidence).
  const tfWeight: Record<string, number> = { monthly: 3, weekly: 2, daily: 1 };
  const ranked = [...patterns]
    .filter((p) => p.completed !== false)
    .sort((a, b) => {
      const aw = tfWeight[a.timeframe ?? "daily"] ?? 0;
      const bw = tfWeight[b.timeframe ?? "daily"] ?? 0;
      if (aw !== bw) return bw - aw;
      return (b.confidence ?? 0) - (a.confidence ?? 0);
    })
    .slice(0, max);

  return (
    <div className="flex flex-wrap gap-1">
      {ranked.map((p, i) => (
        <span
          key={i}
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${chipColor(p.direction)}`}
          title={`${p.kind} · ${p.timeframe ?? "?"} · 신뢰도 ${(p.confidence * 100).toFixed(0)}%`}
        >
          {p.timeframe && (
            <span className="opacity-60 font-mono">
              {TF_BADGE[p.timeframe] ?? p.timeframe[0]}
            </span>
          )}
          <span>{p.kind}</span>
          <HelpTip term={`pattern_${p.kind}`} />
        </span>
      ))}
    </div>
  );
}
