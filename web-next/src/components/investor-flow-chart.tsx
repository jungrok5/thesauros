/**
 * Inline SVG chart of cumulative foreign / institution / individual
 * net buying over the last ~14 trading days. No chart lib — same
 * pattern as equity-curve-chart.tsx, just smaller.
 *
 * Cumulative net (not per-day): a rising line means "consistently
 * accumulating", a falling line means "consistently distributing".
 * Far more informative for "는 세력 흐름" than reading 14 daily bars.
 */

interface Row {
  day: string;
  foreign_net: number | null;
  institution_net: number | null;
  individual_net: number | null;
}

interface Props {
  rows: Row[];   // newest first, length 14ish
}

const W = 560;
const H = 140;
const PAD_X = 8;
const PAD_TOP = 6;
const PAD_BOT = 18;

const COLORS = {
  foreign: "#ef4444",      // rose-500
  institution: "#3b82f6",  // blue-500
  individual: "#9ca3af",   // gray-400
};

function fmtKRWShort(n: number): string {
  if (n === 0) return "0";
  const abs = Math.abs(n);
  const sign = n > 0 ? "+" : "−";
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}억`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(0)}만`;
  return `${sign}${abs.toLocaleString()}`;
}

export function InvestorFlowChart({ rows }: Props) {
  if (rows.length < 2) return null;
  // Sort ascending by day to match left-to-right time axis. The input
  // arrives newest first (DESC); SVG needs oldest first.
  const ordered = [...rows].sort((a, b) => a.day.localeCompare(b.day));

  // Compute cumulative series for each role.
  const xs = ordered.length;
  const cumF: number[] = [];
  const cumI: number[] = [];
  const cumP: number[] = [];
  let f = 0, i = 0, p = 0;
  for (const r of ordered) {
    f += r.foreign_net ?? 0;
    i += r.institution_net ?? 0;
    p += r.individual_net ?? 0;
    cumF.push(f); cumI.push(i); cumP.push(p);
  }
  // Y-axis bounds across all three series. Always include zero so the
  // baseline is meaningful (above = net buy, below = net sell).
  const all = [...cumF, ...cumI, ...cumP, 0];
  const yMin = Math.min(...all);
  const yMax = Math.max(...all);
  // Add small padding so the line doesn't kiss the chart edge.
  const yRange = (yMax - yMin) || 1;
  const yLo = yMin - yRange * 0.08;
  const yHi = yMax + yRange * 0.08;

  const xAt = (idx: number) =>
    PAD_X + (idx / Math.max(1, xs - 1)) * (W - PAD_X * 2);
  const yAt = (v: number) => {
    const t = (v - yLo) / (yHi - yLo);
    return PAD_TOP + (1 - t) * (H - PAD_TOP - PAD_BOT);
  };
  const yZero = yAt(0);

  const pathFor = (series: number[]): string => {
    let d = "";
    series.forEach((v, idx) => {
      d += idx === 0 ? `M ${xAt(idx)} ${yAt(v)}` : ` L ${xAt(idx)} ${yAt(v)}`;
    });
    return d;
  };

  // Tick labels — first + middle + last day.
  const ticks = [0, Math.floor((xs - 1) / 2), xs - 1].filter(
    (v, i, arr) => arr.indexOf(v) === i,
  );

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        preserveAspectRatio="none"
        aria-label="외국인 / 기관 / 개인 누적 순매수"
      >
        {/* Zero baseline — solid line, slightly heavier than grid. */}
        <line
          x1={PAD_X} x2={W - PAD_X} y1={yZero} y2={yZero}
          stroke="currentColor" strokeOpacity="0.25" strokeWidth="1"
        />
        {/* Three cumulative lines */}
        <path d={pathFor(cumF)}
          fill="none" stroke={COLORS.foreign} strokeWidth="1.5" />
        <path d={pathFor(cumI)}
          fill="none" stroke={COLORS.institution} strokeWidth="1.5" />
        <path d={pathFor(cumP)}
          fill="none" stroke={COLORS.individual} strokeWidth="1.5"
          strokeDasharray="3 2" />
        {/* X-axis date ticks */}
        {ticks.map((idx) => (
          <text
            key={idx} x={xAt(idx)} y={H - 4}
            fontSize="9" textAnchor={idx === 0 ? "start" : idx === xs - 1 ? "end" : "middle"}
            fill="currentColor" fillOpacity="0.5"
          >
            {ordered[idx].day.slice(5)}{/* MM-DD */}
          </text>
        ))}
      </svg>
      {/* Legend with running totals */}
      <div className="flex items-center gap-3 flex-wrap text-[10px] mt-1">
        <span className="inline-flex items-center gap-1">
          <span style={{ width: 12, height: 2, background: COLORS.foreign }} />
          외국인 {fmtKRWShort(cumF[cumF.length - 1])}
        </span>
        <span className="inline-flex items-center gap-1">
          <span style={{ width: 12, height: 2, background: COLORS.institution }} />
          기관 {fmtKRWShort(cumI[cumI.length - 1])}
        </span>
        <span className="inline-flex items-center gap-1">
          <span
            style={{
              width: 12, height: 2,
              background: `repeating-linear-gradient(to right, ${COLORS.individual} 0 3px, transparent 3px 5px)`,
            }}
          />
          개인 {fmtKRWShort(cumP[cumP.length - 1])}
        </span>
        <span className="text-muted-foreground">
          ({xs}일 누적 순매수)
        </span>
      </div>
    </div>
  );
}
