/**
 * RowSparkline — tiny inline SVG chart of trailing weekly closes.
 *
 * Renders nothing when fewer than 2 valid points exist. Auto-colors by
 * net direction (first vs last close): green if up, red if down.
 *
 * Dimensions are intentionally small (default 64 × 20) so the sparkline
 * tucks into a table row without growing it. Caller is expected to wrap
 * it inline next to <RowPrice />.
 *
 *   <RowSparkline series={[100, 102, 99, 105, 110]} />
 */
import { cn } from "@/lib/utils";

export function RowSparkline({
  series,
  width = 64,
  height = 20,
  className,
}: {
  series: number[] | null | undefined;
  width?: number;
  height?: number;
  className?: string;
}) {
  if (!series || series.length < 2) return null;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min;
  // Flat line falls back to mid-height — avoid div-by-zero + still
  // shows "no movement" visually.
  const yOf = (v: number) =>
    range === 0
      ? height / 2
      : height - 2 - ((v - min) / range) * (height - 4);
  const xOf = (i: number) =>
    (i / (series.length - 1)) * (width - 2) + 1;

  // Up if last >= first (book treats flat as neutral — keep emerald).
  const up = series[series.length - 1] >= series[0];
  const stroke = up
    ? "stroke-emerald-500/80"
    : "stroke-rose-500/80";

  const points = series.map((v, i) => `${xOf(i)},${yOf(v)}`).join(" ");
  // The last dot makes the latest close visible without a hover.
  const lastX = xOf(series.length - 1);
  const lastY = yOf(series[series.length - 1]);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("inline-block align-middle", className)}
      aria-hidden="true"
    >
      <polyline
        fill="none"
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={stroke}
        points={points}
      />
      <circle
        cx={lastX}
        cy={lastY}
        r={1.5}
        className={up ? "fill-emerald-500" : "fill-rose-500"}
      />
    </svg>
  );
}
