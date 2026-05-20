/**
 * /watchlist loading — mirrors group sections + row cards.
 */
export default function Loading() {
  return (
    <div className="space-y-8 max-w-5xl animate-pulse" aria-label="관심 종목 로딩 중">
      <div className="space-y-2">
        <div className="h-8 w-32 rounded bg-muted" />
        <div className="h-4 w-72 rounded bg-muted/60" />
      </div>

      {/* Group manager details */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="h-5 w-40 rounded bg-muted/60" />
      </div>

      {/* Two section blocks (보유 + 관심) */}
      {Array.from({ length: 2 }).map((_, sec) => (
        <div key={sec} className="space-y-3">
          <div className="h-5 w-32 rounded bg-muted" />
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="rounded-lg border border-border bg-card p-3 flex gap-3 items-center"
              >
                <div className="h-5 w-20 rounded bg-muted" />
                <div className="h-5 flex-1 rounded bg-muted/40" />
                <div className="h-5 w-24 rounded bg-muted/60" />
                <div className="h-5 w-16 rounded bg-muted/40" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
