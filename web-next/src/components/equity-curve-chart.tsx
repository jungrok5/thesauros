/**
 * EquityCurveChart — full-width inline SVG line chart of weekly MTM
 * equity, optional log scale, drawdown shading.
 *
 * Pure SVG (no chart lib). Renders ~900 data points smoothly.
 *
 * Logarithmic Y maps better for 17-year exponential growth: linear
 * crushes the early years near zero.
 */
"use client";

import { useMemo, useState } from "react";

interface EquityPoint {
  d: string;     // ISO date "YYYY-MM-DD"
  e: number;     // equity (KRW)
}

interface Props {
  weekly: EquityPoint[];
  initial: number;
  width?: number;
  height?: number;
}

function fmtKRW(n: number): string {
  if (n >= 100_000_000) return `${(n / 100_000_000).toFixed(1)}억`;
  if (n >= 10_000_000) return `${(n / 10_000_000).toFixed(1)}천만`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(0)}만`;
  return `${Math.round(n).toLocaleString()}`;
}

export function EquityCurveChart({
  weekly,
  initial,
  width = 900,
  height = 320,
}: Props) {
  const [logScale, setLogScale] = useState(true);
  const padLeft = 56;
  const padBottom = 28;
  const padTop = 12;
  const padRight = 12;
  const innerW = width - padLeft - padRight;
  const innerH = height - padTop - padBottom;

  const { points, ddPoints, yTicks, xTicks } = useMemo(() => {
    if (!weekly.length) {
      return { points: "", ddPoints: "", yTicks: [], xTicks: [] };
    }
    const transform = (v: number) => (logScale ? Math.log(v) : v);
    const ys = weekly.map((p) => transform(p.e));
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const rangeY = maxY - minY || 1;

    const xs = weekly.map((_, i) => i / (weekly.length - 1));

    const points = weekly
      .map(
        (p, i) =>
          `${(padLeft + xs[i] * innerW).toFixed(1)},${(
            padTop + (1 - (transform(p.e) - minY) / rangeY) * innerH
          ).toFixed(1)}`,
      )
      .join(" ");

    // Drawdown shading: compute peak-to-current ratio.
    let peak = weekly[0].e;
    const ddPoints = weekly
      .map((p, i) => {
        peak = Math.max(peak, p.e);
        const dd = p.e / peak;             // 0..1
        return `${(padLeft + xs[i] * innerW).toFixed(1)},${(
          padTop + (1 - dd) * innerH * 0.18
        ).toFixed(1)}`;
      })
      .join(" ");

    // Y-axis ticks (5 evenly spaced)
    const yTicks = Array.from({ length: 5 }, (_, k) => {
      const t = k / 4;
      const v = logScale ? Math.exp(minY + t * rangeY) : minY + t * rangeY;
      return {
        y: padTop + (1 - t) * innerH,
        label: fmtKRW(v),
      };
    });

    // X-axis ticks (years on Jan 1)
    const years = Array.from(
      new Set(weekly.map((p) => new Date(p.d).getFullYear())),
    ).sort((a, b) => a - b);
    const xTicks = years
      .filter((_, i, arr) => i % Math.ceil(arr.length / 8) === 0)
      .map((y) => {
        const idx = weekly.findIndex((p) => new Date(p.d).getFullYear() === y);
        if (idx < 0) return null;
        return {
          x: padLeft + (idx / (weekly.length - 1)) * innerW,
          label: String(y),
        };
      })
      .filter((t): t is { x: number; label: string } => t !== null);

    return { points, ddPoints, yTicks, xTicks };
  }, [weekly, logScale, padLeft, padRight, innerW, padTop, innerH]);

  const initialLineY = useMemo(() => {
    if (!weekly.length) return 0;
    const transform = (v: number) => (logScale ? Math.log(v) : v);
    const ys = weekly.map((p) => transform(p.e));
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const rangeY = maxY - minY || 1;
    return padTop + (1 - (transform(initial) - minY) / rangeY) * innerH;
  }, [weekly, initial, logScale, padTop, innerH]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-2 text-xs">
        <label className="flex items-center gap-1 cursor-pointer">
          <input
            type="checkbox"
            checked={logScale}
            onChange={(e) => setLogScale(e.target.checked)}
            className="cursor-pointer"
          />
          <span>로그 스케일</span>
        </label>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-auto rounded-md border border-border bg-card"
        aria-label="17년 backtest equity curve"
      >
        {/* DD shading */}
        <polyline
          points={ddPoints}
          fill="none"
          stroke="#ef4444"
          strokeOpacity={0.35}
          strokeWidth={1}
        />
        {/* Y-axis gridlines + labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={padLeft}
              x2={width - padRight}
              y1={t.y}
              y2={t.y}
              stroke="currentColor"
              strokeOpacity={0.08}
            />
            <text
              x={padLeft - 6}
              y={t.y + 3}
              textAnchor="end"
              fontSize={10}
              fill="currentColor"
              fillOpacity={0.6}
            >
              {t.label}
            </text>
          </g>
        ))}
        {/* Initial line marker */}
        <line
          x1={padLeft}
          x2={width - padRight}
          y1={initialLineY}
          y2={initialLineY}
          stroke="#94a3b8"
          strokeDasharray="3 3"
          strokeOpacity={0.6}
        />
        <text
          x={width - padRight}
          y={initialLineY - 4}
          textAnchor="end"
          fontSize={9}
          fill="#94a3b8"
        >
          초기 1,000만원
        </text>
        {/* Equity line */}
        <polyline
          points={points}
          fill="none"
          stroke="#10b981"
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        {/* X-axis labels */}
        {xTicks.map((t, i) => (
          <text
            key={i}
            x={t.x}
            y={height - 6}
            textAnchor="middle"
            fontSize={10}
            fill="currentColor"
            fillOpacity={0.6}
          >
            {t.label}
          </text>
        ))}
      </svg>
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-emerald-500" /> 평가액 (MTM)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-rose-500/40" /> Drawdown
          shading (peak 대비)
        </span>
      </div>
    </div>
  );
}
