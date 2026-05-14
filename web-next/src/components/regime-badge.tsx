import { cn } from "@/lib/utils";

const REGIME_LABEL: Record<string, { label: string; color: string }> = {
  CONVICTION: {
    label: "확신 (버블 경계)",
    color: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  },
  HOPE: {
    label: "희망 — 본격 상승",
    color: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  },
  HOPE_DOUBT: {
    label: "기대반의심반",
    color: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  },
  FEAR: {
    label: "공포 (위기=기회)",
    color: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  },
  RISK_OFF: {
    label: "리스크 회피",
    color: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  },
  UNKNOWN: {
    label: "데이터 부족",
    color: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  },
};

export function RegimeBadge({
  regime,
  score,
  className,
}: {
  regime: string;
  score: number;
  className?: string;
}) {
  const cfg = REGIME_LABEL[regime] ?? REGIME_LABEL.UNKNOWN;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
        cfg.color,
        className,
      )}
    >
      <span className="font-mono opacity-70">{regime}</span>
      <span>{cfg.label}</span>
      <span className="opacity-70 font-mono text-[10px]">
        score {score >= 0 ? "+" : ""}
        {score.toFixed(2)}
      </span>
    </span>
  );
}
