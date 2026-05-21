/**
 * RowPrice — small two-line cell showing latest weekly close + 1-week
 * change. Used by list-page rows (/screener, /themes/[id]). Empty when
 * no bar data exists for the ticker.
 *
 *   <RowPrice price={...} ticker="005930.KS" />
 *     →  5,300원
 *         +7.2%   (emerald)
 */
import type { LatestPrice } from "@/lib/latest-prices";
import { formatRowPrice } from "@/lib/latest-prices";
import { cn } from "@/lib/utils";

export function RowPrice({
  price,
  ticker,
}: {
  price: LatestPrice | null | undefined;
  ticker: string;
}) {
  if (!price) {
    return <span className="text-[10px] text-muted-foreground">—</span>;
  }
  const pct = price.changePct;
  const pctStr = pct != null ? `${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(1)}%` : "—";
  return (
    <div className="text-right font-mono leading-tight">
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
