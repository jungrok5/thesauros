/**
 * "NEW" badge for signals detected within the last 24h. Without this,
 * a 4-day-old signal looks identical to one that fired this morning —
 * but the actionability is very different (the 4-day-old entry zone
 * has already moved).
 *
 * Freshness must be decided by the SERVER (where the page is rendered)
 * — React's component-purity rule rejects calling Date.now() during
 * render. Callers compute `detectedAt` against their own "now" and
 * pass the result via `freshHoursAgo` (or just pass `isFresh`).
 */

interface Props {
  /** Hours since detection. `undefined` or > threshold → no badge. */
  freshHoursAgo?: number | null;
  /** Hours within which a signal is still "new". */
  withinHours?: number;
}

export function NewBadge({ freshHoursAgo, withinHours = 30 }: Props) {
  if (freshHoursAgo == null) return null;
  if (freshHoursAgo > withinHours) return null;
  return (
    <span
      className="inline-flex items-center px-1 py-0 rounded bg-sky-500/15 text-sky-700 dark:text-sky-300 text-[9px] font-semibold border border-sky-500/30 uppercase tracking-wide"
      title={`detected ${freshHoursAgo.toFixed(1)}h ago`}
    >
      NEW
    </span>
  );
}

/** Server-side helper: hours between a timestamp and now. */
export function hoursSince(detectedAt?: string | Date | null): number | null {
  if (!detectedAt) return null;
  const ts = typeof detectedAt === "string" ? new Date(detectedAt) : detectedAt;
  if (Number.isNaN(ts.getTime())) return null;
  return (Date.now() - ts.getTime()) / 3_600_000;
}
