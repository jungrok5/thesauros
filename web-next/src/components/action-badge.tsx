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

// Amber/zinc "downgrade" styles used when eligibility ≠ "OK" overrides
// a bullish raw `action`. Keeps the badge on the page but stops it from
// shouting 🟢 STRONG_BUY next to a "조건부 — 매수 X" verdict.
const DOWNGRADE_STYLE = {
  CONDITIONAL: {
    label: "조건부",
    klass:
      "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/40",
  },
  WATCH: {
    label: "관망",
    klass:
      "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 border-zinc-500/40",
  },
  AVOID: {
    label: "회피",
    klass:
      "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/40",
  },
} as const;

type EligibilityGrade = "OK" | "CONDITIONAL" | "WATCH" | "AVOID";

export function ActionBadge({
  action,
  size = "md",
  score,
  eligibilityGrade,
  className,
}: {
  action: string;
  size?: "sm" | "md" | "lg";
  score?: number | null;
  /** When the analyzer's eligibility downgraded a bullish action (the
   *  339950.KQ case 2026-05-26: STRONG_BUY ⇒ CONDITIONAL), the badge
   *  must match the verdict card below instead of staying 🟢. */
  eligibilityGrade?: EligibilityGrade | null;
  className?: string;
}) {
  // If a bullish raw action got downgraded by eligibility, render the
  // downgraded chip — otherwise fall back to the raw-action style.
  const isBullish = action === "BUY" || action === "STRONG_BUY";
  const downgraded =
    isBullish && eligibilityGrade && eligibilityGrade !== "OK"
      ? DOWNGRADE_STYLE[eligibilityGrade]
      : null;
  const cfg = downgraded ?? (ACTION_STYLE[action] ?? ACTION_STYLE.HOLD);
  const sizeKlass =
    size === "lg"
      ? "px-3 py-1.5 text-sm"
      : size === "sm"
        ? "px-2 py-0.5 text-[10px]"
        : "px-2.5 py-1 text-xs";
  return (
    <span
      data-action={action}
      data-eligibility={eligibilityGrade ?? "OK"}
      className={cn(
        "inline-flex items-center gap-2 rounded-md border font-medium tracking-wide",
        cfg.klass,
        sizeKlass,
        className,
      )}
      title={
        downgraded
          ? `시스템 분석: ${action} · book_score ${score?.toFixed(2) ?? "—"} ` +
            `· 책 정신 적합도 ${cfg.label} → 한 줄 평 결론 따름`
          : undefined
      }
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
