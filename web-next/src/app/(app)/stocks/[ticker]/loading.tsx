/**
 * /stocks/[ticker] loading skeleton — biggest page (analysis + chart +
 * fundamentals + investor intel cards). Mirrors the actual section
 * stack so the user gets immediate spatial preview while data loads.
 */
export default function Loading() {
  return (
    <div className="space-y-6 max-w-5xl animate-pulse" aria-label="종목 분석 중">
      {/* Back link + ticker header */}
      <div className="space-y-2">
        <div className="h-4 w-16 rounded bg-muted/60" />
        <div className="flex items-baseline gap-3 flex-wrap">
          <div className="h-9 w-40 rounded bg-muted" />
          <div className="h-6 w-24 rounded bg-muted/60" />
          <div className="h-6 w-20 rounded bg-muted/40" />
        </div>
      </div>

      {/* MultiTF matrix + flow chip */}
      <div className="flex gap-2 flex-wrap">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-8 w-24 rounded bg-muted/60" />
        ))}
      </div>

      {/* BookSummaryTable — the central card */}
      <div className="rounded-xl border border-border bg-card p-5 space-y-4">
        <div className="h-6 w-32 rounded bg-muted" />
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex gap-3 items-center">
              <div className="h-5 w-20 rounded bg-muted/60" />
              <div className="h-5 flex-1 rounded bg-muted/30" />
              <div className="h-5 w-16 rounded bg-muted/60" />
            </div>
          ))}
        </div>
      </div>

      {/* Entry plan card */}
      <div className="rounded-lg border-2 border-emerald-500/30 bg-emerald-500/5 p-5 space-y-3">
        <div className="h-4 w-24 rounded bg-muted" />
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 w-12 mx-auto rounded bg-muted/60" />
              <div className="h-7 w-16 mx-auto rounded bg-muted" />
            </div>
          ))}
        </div>
      </div>

      {/* Fundamentals verdicts grid 2x */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="rounded-xl border-2 border-border bg-card p-4 space-y-3">
            <div className="h-5 w-24 rounded bg-muted" />
            <div className="h-4 w-full rounded bg-muted/40" />
            <div className="h-4 w-3/4 rounded bg-muted/40" />
          </div>
        ))}
      </div>

      {/* Chart placeholder */}
      <div className="space-y-2">
        <div className="h-6 w-40 rounded bg-muted" />
        <div className="aspect-video w-full rounded-lg bg-muted/30" />
      </div>
    </div>
  );
}
