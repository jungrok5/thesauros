/**
 * "NEW" badge for signals detected within the last 24h. Without this,
 * a 4-day-old signal looks identical to one that fired this morning —
 * but the actionability is very different (the 4-day-old entry zone
 * has already moved).
 */

interface Props {
  detectedAt?: string | Date | null;
  /** Hours since detection that still count as "new". */
  withinHours?: number;
}

export function NewBadge({ detectedAt, withinHours = 30 }: Props) {
  if (!detectedAt) return null;
  const ts = typeof detectedAt === "string" ? new Date(detectedAt) : detectedAt;
  if (Number.isNaN(ts.getTime())) return null;
  const ageH = (Date.now() - ts.getTime()) / 3_600_000;
  if (ageH > withinHours) return null;
  return (
    <span
      className="inline-flex items-center px-1 py-0 rounded bg-sky-500/15 text-sky-700 dark:text-sky-300 text-[9px] font-semibold border border-sky-500/30 uppercase tracking-wide"
      title={`detected ${ageH.toFixed(1)}h ago`}
    >
      NEW
    </span>
  );
}
