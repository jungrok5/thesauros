"use client";
/**
 * Market-wide investor trend chart with click-to-focus label UX.
 *
 * UX: 라벨(개인/외국인/기관계) 칩을 클릭하면 그 라인만 진하게,
 * 나머지는 흐리게 → 한 주체의 흐름에 집중. 다시 클릭하면 해제(전부 동일).
 * KOSPI / KOSDAQ 탭으로 시장 전환. 같은 패턴이 inline SVG 로 구현돼서
 * lightweight-charts 같은 무거운 lib 없음.
 *
 * Data shape: rows arrive newest-first; chart sorts ASC for left-to-right
 * time axis. Cumulative net (not per-day): 누적이 우상향 = 그 주체가
 * 지속 매수 중. Same convention as per-ticker investor-flow-chart.
 */
import { useState, useMemo } from "react";

export interface MarketRow {
  day: string;
  individual_net: number | null;
  foreign_net: number | null;
  institution_net: number | null;
}

interface Props {
  kospi: MarketRow[];
  kosdaq: MarketRow[];
}

type Series = "individual" | "foreign" | "institution";

const W = 720;
const H = 200;
const PAD_X = 10;
const PAD_TOP = 8;
const PAD_BOT = 22;

const COLORS: Record<Series, string> = {
  foreign: "#ef4444",      // rose-500
  institution: "#3b82f6",  // blue-500
  individual: "#9ca3af",   // gray-400
};

const LABELS: Record<Series, string> = {
  individual: "개인",
  foreign: "외국인",
  institution: "기관계",
};

const ORDER: Series[] = ["foreign", "institution", "individual"];

function fmtKRWShort(n: number): string {
  // Backend stores 백만 (millions). Convert to 억 for legibility.
  // 1억 = 100백만.
  if (n === 0) return "0";
  const eok = n / 100;
  const abs = Math.abs(eok);
  const sign = n > 0 ? "+" : "−";
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)}조`;
  if (abs >= 1) return `${sign}${abs.toFixed(0)}억`;
  return `${sign}${(abs * 100).toFixed(0)}백만`;
}

function netOf(r: MarketRow, key: Series): number {
  if (key === "individual") return r.individual_net ?? 0;
  if (key === "foreign") return r.foreign_net ?? 0;
  return r.institution_net ?? 0;
}

interface ChartViewProps {
  rows: MarketRow[];
  focus: Series | null;
}

function ChartView({ rows, focus }: ChartViewProps) {
  const sorted = useMemo(
    () => [...rows].sort((a, b) => a.day.localeCompare(b.day)),
    [rows],
  );
  const xs = sorted.length;
  if (xs < 2) {
    return (
      <div className="text-xs text-muted-foreground p-3 text-center">
        데이터가 1일치뿐이라 추세를 그릴 수 없습니다 (cron 매일 17 KST 누적).
      </div>
    );
  }
  const cum: Record<Series, number[]> = {
    individual: [],
    foreign: [],
    institution: [],
  };
  const running: Record<Series, number> = {
    individual: 0,
    foreign: 0,
    institution: 0,
  };
  for (const r of sorted) {
    for (const k of ORDER) {
      running[k] += netOf(r, k);
      cum[k].push(running[k]);
    }
  }
  const all = [...cum.individual, ...cum.foreign, ...cum.institution, 0];
  const yMin = Math.min(...all);
  const yMax = Math.max(...all);
  const yRange = (yMax - yMin) || 1;
  const yLo = yMin - yRange * 0.08;
  const yHi = yMax + yRange * 0.08;

  const xAt = (i: number) =>
    PAD_X + (i / Math.max(1, xs - 1)) * (W - PAD_X * 2);
  const yAt = (v: number) => {
    const t = (v - yLo) / (yHi - yLo);
    return PAD_TOP + (1 - t) * (H - PAD_TOP - PAD_BOT);
  };
  const yZero = yAt(0);

  const pathFor = (series: number[]): string => {
    let d = "";
    series.forEach((v, i) => {
      d += i === 0 ? `M ${xAt(i)} ${yAt(v)}` : ` L ${xAt(i)} ${yAt(v)}`;
    });
    return d;
  };

  const tickIdx = [0, Math.floor((xs - 1) / 2), xs - 1].filter(
    (v, i, a) => a.indexOf(v) === i,
  );

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-auto"
      preserveAspectRatio="none"
      aria-label="시장 전체 누적 순매수 — 개인 / 외국인 / 기관계"
    >
      <line
        x1={PAD_X} x2={W - PAD_X} y1={yZero} y2={yZero}
        stroke="currentColor" strokeOpacity="0.25" strokeWidth="1"
      />
      {ORDER.map((k) => {
        const isFocused = focus === null || focus === k;
        return (
          <path
            key={k}
            d={pathFor(cum[k])}
            fill="none"
            stroke={COLORS[k]}
            strokeWidth={isFocused ? (focus === k ? 2.4 : 1.5) : 1.5}
            strokeOpacity={isFocused ? 1 : 0.18}
            strokeDasharray={k === "individual" ? "4 2" : undefined}
          />
        );
      })}
      {tickIdx.map((i) => (
        <text
          key={i} x={xAt(i)} y={H - 5}
          fontSize="10"
          textAnchor={i === 0 ? "start" : i === xs - 1 ? "end" : "middle"}
          fill="currentColor" fillOpacity="0.5"
        >
          {sorted[i].day.slice(5)}
        </text>
      ))}
    </svg>
  );
}

export function MarketInvestorTrendChart({ kospi, kosdaq }: Props) {
  const [market, setMarket] = useState<"KOSPI" | "KOSDAQ">("KOSPI");
  const [focus, setFocus] = useState<Series | null>(null);
  const rows = market === "KOSPI" ? kospi : kosdaq;

  const cumulative = useMemo<Record<Series, number>>(() => {
    const acc: Record<Series, number> = { individual: 0, foreign: 0, institution: 0 };
    for (const r of rows) {
      acc.individual += r.individual_net ?? 0;
      acc.foreign += r.foreign_net ?? 0;
      acc.institution += r.institution_net ?? 0;
    }
    return acc;
  }, [rows]);

  const dayCount = rows.length;

  return (
    <section className="rounded-lg border border-border bg-card p-3 space-y-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <div className="text-sm font-semibold tracking-tight">
            시장 전체 매매 동향 (누적 {dayCount}일)
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            라벨을 누르면 그 주체만 진하게 — 누가 사고 누가 파는지 한눈에. (Naver 시세, 매일 17 KST 갱신)
          </p>
        </div>
        <div role="tablist" aria-label="시장 선택" className="inline-flex rounded-md border border-border overflow-hidden text-xs">
          {(["KOSPI", "KOSDAQ"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={market === m}
              onClick={() => setMarket(m)}
              className={`px-3 py-1 transition-colors ${
                market === m
                  ? "bg-foreground text-background"
                  : "bg-card hover:bg-muted/40"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </header>

      <div role="group" aria-label="라벨 포커스" className="flex items-center gap-2 flex-wrap text-xs">
        {ORDER.map((k) => {
          const isFocused = focus === k;
          const isDimmed = focus !== null && !isFocused;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setFocus(isFocused ? null : k)}
              aria-pressed={isFocused}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition ${
                isFocused
                  ? "border-foreground bg-foreground/10"
                  : isDimmed
                    ? "border-border/40 opacity-50 hover:opacity-80"
                    : "border-border hover:bg-muted/40"
              }`}
            >
              <span
                aria-hidden
                style={{
                  width: 14, height: 2,
                  background: k === "individual"
                    ? `repeating-linear-gradient(to right, ${COLORS[k]} 0 3px, transparent 3px 5px)`
                    : COLORS[k],
                }}
              />
              <span className="font-medium">{LABELS[k]}</span>
              <span className="text-muted-foreground font-mono">
                {fmtKRWShort(cumulative[k])}
              </span>
            </button>
          );
        })}
        {focus !== null && (
          <button
            type="button"
            onClick={() => setFocus(null)}
            className="text-muted-foreground hover:text-foreground text-[11px] underline-offset-2 hover:underline ml-1"
          >
            전체 보기
          </button>
        )}
      </div>

      <ChartView rows={rows} focus={focus} />

      <footer className="text-[10px] text-muted-foreground">
        값은 KRW 백만 단위, 양수 = 순매수 / 음수 = 순매도. 누적이 우상향이면 그 주체가 지속 매수 중.
      </footer>
    </section>
  );
}
