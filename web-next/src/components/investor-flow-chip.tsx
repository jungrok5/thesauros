/**
 * Companion indicator: did 외국인·기관 (foreign + institution) net-buy this
 * ticker over the last 5 trading days? When BOTH are accumulating, that's
 * a strong corroboration of a book technical-pattern signal — many
 * traders read "smart money flow" as a tiebreaker between two otherwise
 * identical setups.
 *
 * KR-only by data availability (investor_flow comes from Naver Finance
 * frgn page). US tickers show no chip.
 */
import { HelpTip } from "@/components/help-tip";

export interface FlowSummary {
  /** Sum of net krw over last 5 trading days. Positive = net-buy. */
  foreignNet: number;
  institutionNet: number;
  /** Latest day for which we have data. */
  latestDay: string | null;
}

export function classifyFlow(s: FlowSummary | null | undefined): {
  label: string; tone: "bull" | "bear" | "mixed" | "none";
} {
  if (!s) return { label: "", tone: "none" };
  const f = s.foreignNet > 0;
  const i = s.institutionNet > 0;
  if (f && i) return { label: "외인+기관 동행 매수", tone: "bull" };
  if (!f && !i) return { label: "외인+기관 동행 매도", tone: "bear" };
  if (f) return { label: "외인만 순매수", tone: "mixed" };
  return { label: "기관만 순매수", tone: "mixed" };
}

interface Props {
  flow?: FlowSummary | null;
  compact?: boolean;
}

export function InvestorFlowChip({ flow, compact }: Props) {
  if (!flow) return null;
  const c = classifyFlow(flow);
  const style =
    c.tone === "bull"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/40"
      : c.tone === "bear"
        ? "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/40"
        : "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/40";
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${style}`}
      title={`외인 ${(flow.foreignNet / 1e9).toFixed(1)}B · 기관 ${(flow.institutionNet / 1e9).toFixed(1)}B (5일 합계)`}
    >
      <span>{compact ? c.label.split(" ")[0] : c.label}</span>
      <HelpTip term="investor_flow" />
    </span>
  );
}
