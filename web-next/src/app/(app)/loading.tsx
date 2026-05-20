/**
 * Default loading skeleton for ALL pages under (app)/.
 *
 * Next.js shows this UI immediately when the user clicks a nav link,
 * while the server renders the actual page.tsx in the background.
 * Replaces the "blank screen 1-2s" feeling the user reported
 * (2026-05-20) — feedback now feels instant even though server
 * data fetches take the same time.
 *
 * Pages that need a more specific skeleton (matching their layout
 * shape, e.g. /watchlist with group sections) override this with
 * their own loading.tsx file.
 */
export default function Loading() {
  return (
    <div className="space-y-6 max-w-5xl animate-pulse" aria-label="로딩 중">
      {/* Title placeholder */}
      <div className="space-y-2">
        <div className="h-8 w-48 rounded bg-muted" />
        <div className="h-4 w-80 rounded bg-muted/60" />
      </div>

      {/* Generic card grid — works for dashboard / screener / watchlist */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="rounded-lg border border-border bg-card p-4 space-y-3"
          >
            <div className="h-4 w-24 rounded bg-muted" />
            <div className="h-7 w-32 rounded bg-muted/80" />
            <div className="h-3 w-full rounded bg-muted/40" />
            <div className="h-3 w-3/4 rounded bg-muted/40" />
          </div>
        ))}
      </div>

      {/* Bottom block — table-ish placeholder */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="h-9 bg-muted/30" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="px-4 py-3 border-t border-border flex gap-4">
            <div className="h-4 w-24 rounded bg-muted/60" />
            <div className="h-4 flex-1 rounded bg-muted/40" />
            <div className="h-4 w-16 rounded bg-muted/60" />
          </div>
        ))}
      </div>
    </div>
  );
}
