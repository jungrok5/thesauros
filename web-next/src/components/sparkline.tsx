/**
 * Tiny inline SVG sparkline of recent closing prices, so the recommendations
 * row gives "what does the chart look like?" at a glance — instead of forcing
 * the user to click into every ticker to see whether the trend is steep,
 * choppy, or flat.
 *
 * The component is intentionally lightweight (no charting lib) so 50 rows
 * render without measurable cost.
 */

interface Props {
  closes: number[];
  width?: number;
  height?: number;
  /**
   * Color override. By default, derives green/red from the first-to-last
   * delta sign so the eye can scan "winners vs losers".
   */
  color?: string;
}

export function Sparkline({ closes, width = 96, height = 24, color }: Props) {
  if (!closes?.length || closes.length < 2) {
    return (
      <div
        className="text-[9px] text-muted-foreground/60 flex items-center justify-center"
        style={{ width, height }}
      >
        —
      </div>
    );
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const step = width / (closes.length - 1);
  const points = closes
    .map((c, i) => `${(i * step).toFixed(2)},${(height - ((c - min) / range) * height).toFixed(2)}`)
    .join(" ");
  const delta = closes[closes.length - 1] - closes[0];
  const stroke = color ?? (delta >= 0 ? "#10b981" : "#ef4444");
  const lastX = ((closes.length - 1) * step).toFixed(2);
  const lastY = (height - ((closes[closes.length - 1] - min) / range) * height).toFixed(2);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r="1.5" fill={stroke} />
    </svg>
  );
}
