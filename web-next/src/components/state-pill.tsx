import { cn } from "@/lib/utils";

const STATE_STYLES: Record<string, string> = {
  BULL: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  NEUTRAL: "bg-zinc-500/10 text-zinc-300 border-zinc-500/30",
  CAUTION: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  BEAR: "bg-rose-500/10 text-rose-400 border-rose-500/30",
};

export function StatePill({ state }: { state: string }) {
  const klass = STATE_STYLES[state] ?? STATE_STYLES.NEUTRAL;
  return (
    <span
      className={cn(
        "inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium tracking-wider",
        klass,
      )}
    >
      {state}
    </span>
  );
}
