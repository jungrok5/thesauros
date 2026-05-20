/**
 * /dashboard loading — market ticker + action card + indicator grid.
 */
export default function Loading() {
  return (
    <div className="space-y-6 max-w-7xl animate-pulse" aria-label="거시 환경 로딩 중">
      <div className="space-y-2">
        <div className="h-8 w-40 rounded bg-muted" />
        <div className="h-4 w-96 rounded bg-muted/60" />
      </div>

      {/* MarketTicker band */}
      <div className="rounded-lg border border-border bg-card p-3 flex gap-4 overflow-hidden">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="shrink-0 h-12 w-32 rounded bg-muted/60" />
        ))}
      </div>

      {/* SeasonalBanner */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="h-5 w-3/4 rounded bg-muted/40" />
      </div>

      {/* MarketActionCard — big hero */}
      <div className="rounded-xl border-2 border-border bg-card p-6 space-y-4">
        <div className="h-6 w-48 rounded bg-muted" />
        <div className="h-10 w-full rounded bg-muted/40" />
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 w-12 rounded bg-muted/60" />
              <div className="h-6 w-10 rounded bg-muted" />
            </div>
          ))}
        </div>
      </div>

      {/* 핵심 지표 grid */}
      <div className="space-y-3">
        <div className="h-5 w-32 rounded bg-muted" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-border bg-card p-4 space-y-2">
              <div className="h-4 w-24 rounded bg-muted/60" />
              <div className="h-7 w-20 rounded bg-muted" />
              <div className="h-3 w-full rounded bg-muted/30" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
