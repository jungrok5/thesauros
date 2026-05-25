/**
 * RowPrice — small two-line cell showing latest weekly close + 1-week
 * change. Used by list-page rows (/screener). Empty when
 * no bar data exists for the ticker.
 *
 *   <RowPrice price={...} ticker="005930.KS" />
 *     →  5,300원
 *         +7.2%   (emerald)
 */
import type { LatestPrice } from "@/lib/latest-prices";
import { formatRowPrice } from "@/lib/latest-prices";
import { RowSparkline } from "@/components/row-sparkline";
import { cn } from "@/lib/utils";

export function RowPrice({
  price,
  ticker,
  showSparkline = true,
}: {
  price: LatestPrice | null | undefined;
  ticker: string;
  /** When true (default), renders a small inline sparkline of trailing
   *  weekly closes above the price. Set false to drop it (e.g. for very
   *  narrow contexts). */
  showSparkline?: boolean;
}) {
  if (!price) {
    return <span className="text-[10px] text-muted-foreground">—</span>;
  }
  const pct = price.changePct;
  const pctStr = pct != null ? `${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(1)}%` : "—";
  return (
    <div className="text-right font-mono leading-tight">
      {showSparkline && price.series && price.series.length >= 2 && (
        <RowSparkline series={price.series} className="block ml-auto" />
      )}
      <div className="text-foreground">{formatRowPrice(price.close, ticker)}</div>
      <div
        className={cn(
          "text-[10px]",
          pct == null
            ? "text-muted-foreground"
            : pct >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-600 dark:text-rose-400",
        )}
      >
        {pctStr}
      </div>
    </div>
  );
}
