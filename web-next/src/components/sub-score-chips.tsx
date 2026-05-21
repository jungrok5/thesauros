/**
 * SubScoreChips — small inline chips showing the *sub-scores* hidden
 * inside book_score's 1-D aggregate. Lets the user distinguish two
 * STRONG_BUY 1.00 stocks at a glance:
 *
 *   - one with volume surge + safe75 + catalyst 2 weeks ago
 *   - one that just has the trend dimension going for it
 *
 * Surface 3 dimensions when present:
 *   📊 거래량 ratio (volume_case bucket — 폭증 / 매집 / 분배 / 감소)
 *   🎯 4등분선 zone (safe75 / warn50 / danger25 / broken)
 *   🔥 catalyst 직후 N주 (장대양봉 + 거래량 catalyst, N <= 8 weeks 만)
 *
 * No chip when its source data is absent. Rendered together as a tight
 * flex row so they fit inside a screener table cell or stock-list card.
 */

const VOLUME_CASE_BUCKET: Record<number, { emoji: string; label: string; cls: string }> = {
  // case 3 + 9 = 매수 강한 폭증 (책 p365-369)
  3: { emoji: "📊", label: "바닥 폭증",   cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  9: { emoji: "📊", label: "급등 폭증",   cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  // case 7 + 12 = bullish accumulation 감소 (책: 매물 소진, 매수 자리)
  7: { emoji: "💧", label: "매집 감소",   cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300" },
  12: { emoji: "💧", label: "수렴 감소",   cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300" },
  // case 8 / 10 / 11 = bearish (분배 / 천장)
  8:  { emoji: "🌪️", label: "분배 의심", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
  10: { emoji: "🌪️", label: "천장 폭증", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
  11: { emoji: "🌪️", label: "세력 위임", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
};

const QUARTER_ZONE: Record<string, { emoji: string; label: string; cls: string }> = {
  safe75:   { emoji: "🎯", label: "safe75",   cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  warn50:   { emoji: "🎯", label: "warn50",   cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  danger25: { emoji: "🎯", label: "danger25", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
  broken:   { emoji: "🎯", label: "broken",   cls: "bg-rose-500/20 text-rose-700 dark:text-rose-300 line-through" },
};

export function SubScoreChips({
  volumeCase,
  quarterZone,
  catalystBarsSince,
  className,
}: {
  volumeCase?: number | null;
  quarterZone?: string | null;
  catalystBarsSince?: number | null;
  className?: string;
}) {
  const chips: React.ReactNode[] = [];

  if (volumeCase != null && VOLUME_CASE_BUCKET[volumeCase]) {
    const v = VOLUME_CASE_BUCKET[volumeCase];
    chips.push(
      <span
        key="vol"
        className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ${v.cls}`}
        title={`거래량 case ${volumeCase}: ${v.label}`}
      >
        {v.emoji} {v.label}
      </span>,
    );
  }

  if (quarterZone && QUARTER_ZONE[quarterZone]) {
    const q = QUARTER_ZONE[quarterZone];
    chips.push(
      <span
        key="zone"
        className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ${q.cls}`}
        title={`4등분선 zone: ${q.label}`}
      >
        {q.emoji} {q.label}
      </span>,
    );
  }

  // catalyst freshness — only chip when bars_since <= 8 weeks (still
  // reasonably fresh). Past that the chart's moved on.
  if (
    catalystBarsSince != null
    && Number.isFinite(catalystBarsSince)
    && catalystBarsSince >= 0
    && catalystBarsSince <= 8
  ) {
    chips.push(
      <span
        key="cat"
        className="inline-flex items-center rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 text-[10px]"
        title={`장대양봉 catalyst ${catalystBarsSince}주 전`}
      >
        🔥 catalyst-{catalystBarsSince}w
      </span>,
    );
  }

  if (chips.length === 0) return null;

  return (
    <div className={`flex flex-wrap items-center gap-1 ${className ?? ""}`}>
      {chips}
    </div>
  );
}
