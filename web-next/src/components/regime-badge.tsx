import { cn } from "@/lib/utils";
import { HelpTip } from "@/components/help-tip";

const REGIME_LABEL: Record<string, { label: string; color: string; tip?: string }> = {
  CONVICTION: {
    label: "확신 (버블 경계)",
    color: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    tip:
      "확신 단계: 시장 참여자 다수가 강세를 확신하는 후기 상승 국면. " +
      "수익은 가장 클 수 있으나 버블/조정 위험이 동시에 커진다.",
  },
  HOPE: {
    label: "희망 — 본격 상승",
    color: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    tip:
      "희망 단계: 경기 회복 + 유동성 + 심리 모두 우호. " +
      "다수 종목이 동반 상승하는 강세장, 추세 추종 매수에 가장 유리한 환경.",
  },
  HOPE_DOUBT: {
    label: "기대반의심반",
    color: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    tip:
      "기대와 의심이 교차하는 중간 국면. 일부 지표는 회복, 일부는 둔화. " +
      "선별적 매수 + 변동성 관리.",
  },
  FEAR: {
    label: "공포 (위기=기회)",
    color: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    tip:
      "공포 단계: 극단적 매도세로 가격이 과도하게 빠진 구간. " +
      "장기적으로는 매수 기회가 되는 경우가 많아 분할매수 시점으로 본다.",
  },
  RISK_OFF: {
    label: "리스크 회피",
    color: "bg-orange-500/15 text-orange-300 border-orange-500/30",
    tip:
      "리스크 회피 국면: VIX 상승, 채권 선호 등 안전자산으로 자금이 몰리는 시점. " +
      "현금 비중 늘리고 보수적으로 운용.",
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
      <span>
        {cfg.tip ? (
          <HelpTip title={`${regime} — ${cfg.label}`} body={cfg.tip}>
            {cfg.label}
          </HelpTip>
        ) : (
          cfg.label
        )}
      </span>
      <span className="opacity-70 font-mono text-[10px]">
        score {score >= 0 ? "+" : ""}
        {score.toFixed(2)}
      </span>
    </span>
  );
}
