/**
 * Shared color tokens for watchlist groups.
 *
 * Lives in its own module (no "use client") so BOTH the server-rendered
 * page.tsx AND the client GroupManager component can import without
 * breaking Next.js's module-graph boundary (clients can't share
 * runtime exports back to server).
 *
 * Bug fixed 2026-05-20: previously `groupColorClass` lived inside
 * group-manager-client.tsx which is "use client" — the server's import
 * triggered a Vercel runtime error (ERROR 1025776953) on /watchlist.
 */

export const COLOR_OPTIONS: ReadonlyArray<{ key: string; label: string; cls: string }> = [
  { key: "emerald", label: "초록", cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40" },
  { key: "sky",     label: "파랑", cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/40" },
  { key: "amber",   label: "주황", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/40" },
  { key: "violet",  label: "보라", cls: "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/40" },
  { key: "rose",    label: "빨강", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/40" },
  { key: "zinc",    label: "회색", cls: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 border-zinc-500/40" },
];

export function groupColorClass(color: string | null | undefined): string {
  if (!color) return "bg-muted text-muted-foreground border-border";
  const o = COLOR_OPTIONS.find((c) => c.key === color);
  return o?.cls ?? "bg-muted text-muted-foreground border-border";
}
