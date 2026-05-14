import { cn } from "@/lib/utils";

const ACTION_STYLE: Record<string, { label: string; klass: string }> = {
  STRONG_BUY: {
    label: "STRONG BUY",
    klass:
      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  },
  BUY: {
    label: "BUY",
    klass:
      "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  },
  HOLD: {
    label: "HOLD",
    klass:
      "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300 border-zinc-500/30",
  },
  SELL: {
    label: "SELL",
    klass:
      "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/40",
  },
  SELL_OR_SHORT: {
    label: "SELL / SHORT",
    klass:
      "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/40",
  },
  AVOID: {
    label: "AVOID",
    klass:
      "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/40",
  },
};

export function ActionBadge({
  action,
  size = "md",
  score,
  className,
}: {
  action: string;
  size?: "sm" | "md" | "lg";
  score?: number | null;
  className?: string;
}) {
  const cfg = ACTION_STYLE[action] ?? ACTION_STYLE.HOLD;
  const sizeKlass =
    size === "lg"
      ? "px-3 py-1.5 text-sm"
      : size === "sm"
        ? "px-2 py-0.5 text-[10px]"
        : "px-2.5 py-1 text-xs";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md border font-medium tracking-wide",
        cfg.klass,
        sizeKlass,
        className,
      )}
    >
      <span>{cfg.label}</span>
      {score !== undefined && score !== null && (
        <span className="opacity-70 font-mono text-[10px]">
          {score >= 0 ? "+" : ""}
          {score.toFixed(2)}
        </span>
      )}
    </span>
  );
}
