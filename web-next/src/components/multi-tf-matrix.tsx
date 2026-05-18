/**
 * 3-cell visualization of the book's multi-timeframe trend stack.
 *
 * Book's primary signal hierarchy is 월봉 240MA > 월봉 10MA > 주봉 10MA >
 * 일봉 정배열. This component shows each timeframe's stance as a colored
 * pill so the eye can scan and pick the names where all three align.
 */

interface TrendState {
  label?: string | null;
  above_ma_10?: boolean | null;
  above_ma_240?: boolean | null;
  alignment_score?: number | null;
  overall_score?: number | null;
}

interface Props {
  monthly?: TrendState | null;
  weekly?: TrendState | null;
  daily?: TrendState | null;
}

const TF_LABEL = { monthly: "월", weekly: "주", daily: "일" } as const;

function cellColor(s?: TrendState | null): { bg: string; text: string; symbol: string } {
  if (!s) return { bg: "bg-muted/40", text: "text-muted-foreground/50", symbol: "·" };
  const ma10 = s.above_ma_10;
  const ma240 = s.above_ma_240;
  const score = s.overall_score ?? 0;
  if (ma10 && (ma240 || ma240 === null) && score >= 0.6) {
    return {
      bg: "bg-emerald-500/15",
      text: "text-emerald-700 dark:text-emerald-300",
      symbol: "↑",
    };
  }
  if (ma10) {
    return {
      bg: "bg-yellow-500/15",
      text: "text-yellow-700 dark:text-yellow-300",
      symbol: "→",
    };
  }
  if (ma240 === false) {
    return {
      bg: "bg-rose-500/15",
      text: "text-rose-700 dark:text-rose-300",
      symbol: "✕",
    };
  }
  return {
    bg: "bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-300",
    symbol: "↓",
  };
}

export function MultiTFMatrix({ monthly, weekly, daily }: Props) {
  const cells: Array<[keyof typeof TF_LABEL, TrendState | null | undefined]> = [
    ["monthly", monthly],
    ["weekly", weekly],
    ["daily", daily],
  ];
  return (
    <div
      className="inline-flex items-center rounded border border-border overflow-hidden text-[10px] font-medium"
      title="월/주/일 추세 정렬 (책의 신호 우선순위)"
    >
      {cells.map(([tf, s]) => {
        const { bg, text, symbol } = cellColor(s);
        return (
          <div
            key={tf}
            className={`flex flex-col items-center justify-center px-1.5 py-0.5 ${bg} ${text} border-r border-border last:border-r-0`}
            title={
              s?.label
                ? `${TF_LABEL[tf]}봉: ${s.label}` +
                  (s.alignment_score != null
                    ? ` · 정렬 ${(s.alignment_score * 100).toFixed(0)}%`
                    : "")
                : `${TF_LABEL[tf]}봉: 데이터 없음`
            }
          >
            <span className="opacity-60 leading-none">{TF_LABEL[tf]}</span>
            <span className="leading-none">{symbol}</span>
          </div>
        );
      })}
    </div>
  );
}
