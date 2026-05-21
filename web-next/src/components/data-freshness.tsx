/**
 * <DataFreshness> — small inline chip showing when the data was last
 * refreshed + an amber warning when the row is stale relative to its
 * expected cadence.
 *
 * Why this exists: the stock detail page mixes data with very different
 * refresh cadences (analysis weekly, fundamentals quarterly, investor
 * flow daily, holders event-driven). Without an "as-of" label on each
 * card, users assume everything is current — and a "PER 12.3" displayed
 * from a Q1 filing six months ago reads identically to a fresh value.
 * The 088350.KS verdict bug (analyzer's future-stamped `as_of` reading
 * as "분석은 미래") was the same class of problem.
 *
 * UI: text-[10px] muted chip when fresh, amber when stale. Renders
 * nothing when `asOf` is null/invalid (don't lie about absent data).
 *
 * Cadence presets define the "stale threshold" — past which the chip
 * flips color and adds a short reason. Tuned to leave headroom for one
 * missed cron (so a daily refresh that skipped one weekday stays green).
 */
import { cn } from "@/lib/utils";

export type Cadence =
  | "realtime"    // < 1h normal, then stale (rare — used by realtime API
                  //   fetches like LastClose which already prints time)
  | "daily"       // < 7d normal (covers weekend + 1-day cron miss)
  | "weekly"      // < 14d normal (one missed Friday)
  | "monthly"     // < 45d normal
  | "quarterly"   // < 120d normal (one missed quarter cycle = ~90d + buffer)
  | "yearly";     // < 400d normal

const STALE_DAYS: Record<Cadence, number> = {
  realtime: 1 / 24,
  daily: 7,
  weekly: 14,
  monthly: 45,
  quarterly: 120,
  yearly: 400,
};

const CADENCE_LABEL: Record<Cadence, string> = {
  realtime: "실시간",
  daily: "일별 갱신",
  weekly: "주간 갱신",
  monthly: "월별 갱신",
  quarterly: "분기 갱신",
  yearly: "연간 갱신",
};

interface Props {
  /** ISO timestamp (date or full datetime). Anything else → no render. */
  asOf?: string | Date | null;
  /** Expected refresh cadence — determines stale threshold + label. */
  cadence: Cadence;
  /** Optional prefix — e.g. "분석" / "기준" / "갱신". Default: "기준". */
  label?: string;
  /** Inline (default) or block. Block adds margin-top. */
  block?: boolean;
}

function daysAgo(asOf: Date, now: Date): number {
  return Math.floor((now.getTime() - asOf.getTime()) / 86_400_000);
}

function ageLabel(days: number): string {
  // Negative days = future-stamped (e.g. weekly bar_date is the upcoming
  // Friday close). Treat as "이번 주" — saying "N일 후" reads as "분석이
  // 미래" which is the 088350.KS 2026-05-20 confusion we already fixed
  // in BookVerdict.
  if (days <= 0) return "이번 주";
  if (days === 1) return "어제";
  if (days < 14) return `${days}일 전`;
  if (days < 60) return `${Math.round(days / 7)}주 전`;
  if (days < 730) return `${Math.round(days / 30)}개월 전`;
  return `${Math.round(days / 365)}년 전`;
}

export function DataFreshness({
  asOf,
  cadence,
  label = "기준",
  block = false,
}: Props) {
  if (!asOf) return null;
  const asOfDate = typeof asOf === "string" ? new Date(asOf) : asOf;
  if (!(asOfDate instanceof Date) || Number.isNaN(asOfDate.getTime())) {
    return null;
  }
  const now = new Date();
  const days = daysAgo(asOfDate, now);
  const stale = days > STALE_DAYS[cadence];
  // Date string in YYYY-MM-DD (use UTC-shifted local — same display the
  // analyzer chip uses, no timezone surprises).
  const dateStr = asOfDate.toISOString().slice(0, 10);
  const age = ageLabel(days);

  const wrap = block ? "mt-1" : "inline-block";
  return (
    <span
      className={cn(
        wrap,
        "rounded-md border px-1.5 py-0.5 text-[10px] font-medium leading-none whitespace-nowrap",
        stale
          ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "border-border bg-muted/30 text-muted-foreground",
      )}
      title={`${CADENCE_LABEL[cadence]} — ${stale ? "갱신 지연" : "정상"}`}
    >
      🗓️ {dateStr} {label} · {age}
      {stale && (
        <span className="ml-1 opacity-80">· {CADENCE_LABEL[cadence]} 지연</span>
      )}
    </span>
  );
}
