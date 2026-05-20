/**
 * /screener loading — preset cards + result table placeholder.
 */
export default function Loading() {
  return (
    <div className="space-y-6 max-w-5xl animate-pulse" aria-label="스크리너 로딩 중">
      <div className="space-y-2">
        <div className="h-8 w-40 rounded bg-muted" />
        <div className="h-4 w-96 rounded bg-muted/60" />
      </div>
      {/* Preset card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="rounded-lg border-2 border-border bg-card p-4 space-y-2">
            <div className="h-6 w-3/4 rounded bg-muted" />
            <div className="h-3 w-full rounded bg-muted/40" />
            <div className="h-3 w-2/3 rounded bg-muted/40" />
          </div>
        ))}
      </div>
      {/* Result section */}
      <div className="rounded-xl border-2 border-border bg-card p-4 space-y-3">
        <div className="h-6 w-1/2 rounded bg-muted" />
        <div className="flex gap-2 flex-wrap">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-6 w-20 rounded-full bg-muted/60" />
          ))}
        </div>
      </div>
    </div>
  );
}
