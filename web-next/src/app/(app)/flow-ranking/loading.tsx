/**
 * /flow-ranking loading — 두 ranking table placeholder.
 */
export default function Loading() {
  return (
    <div className="space-y-6 max-w-5xl animate-pulse" aria-label="랭킹 로딩 중">
      <div className="space-y-2">
        <div className="h-8 w-48 rounded bg-muted" />
        <div className="h-4 w-96 rounded bg-muted/60" />
      </div>
      <div className="rounded-xl border-2 border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
        <div className="h-3 w-32 rounded bg-muted/60" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-3 w-full rounded bg-muted/40" />
        ))}
      </div>
      {Array.from({ length: 2 }).map((_, sec) => (
        <div key={sec} className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="h-9 bg-muted/30" />
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="px-4 py-2 border-t border-border flex gap-3">
              <div className="h-5 w-6 rounded bg-muted/40" />
              <div className="h-5 flex-1 rounded bg-muted/60" />
              <div className="h-5 w-16 rounded bg-muted/40" />
              <div className="h-5 w-16 rounded bg-muted/40" />
              <div className="h-5 w-16 rounded bg-muted/60" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
