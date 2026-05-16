"use client";

import { useEffect, useRef, useState } from "react";
import type {
  IChartApi,
  ISeriesApi,
  CandlestickData,
  LineData,
  Time,
} from "lightweight-charts";

type Timeframe = "daily" | "weekly" | "monthly";

interface ChartBar {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface MAPoint {
  t: number;
  value: number;
}

interface PatternBlock {
  kind: string;
  direction: "bullish" | "bearish";
  confidence: number;
  entry: number | null;
  stop: number | null;
  target: number | null;
  detected_at: string | null;
  extra?: Record<string, unknown>;
}

interface QuarterLines {
  price_low: number;
  price_25: number;
  price_50: number;
  price_75: number;
  price_high: number;
  candle_t: number;
}

interface ChartResponse {
  ticker: string;
  timeframe: Timeframe;
  bars: ChartBar[];
  mas: Record<string, MAPoint[]>;
  patterns: PatternBlock[];
  quarter_lines: QuarterLines | null;
  last_candle: unknown;
}

const MA_COLORS: Record<string, string> = {
  ma_10:  "#22c55e",   // green — 진정한 추세선
  ma_20:  "#0ea5e9",
  ma_60:  "#a855f7",
  ma_120: "#f97316",
  ma_240: "#ef4444",   // red — 강력한 지지/저항
};

const QUARTER_COLORS = {
  high: "#9ca3af",
  p75:  "#10b981",   // safe zone
  p50:  "#eab308",   // warning
  p25:  "#ef4444",   // absolute floor
  low:  "#374151",
};

interface Props {
  ticker: string;
  timeframe?: Timeframe;
  years?: number;
  height?: number;
}

export function BookChart({ ticker, timeframe: initialTf = "weekly", years = 2, height = 480 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tf, setTf] = useState<Timeframe>(initialTf);
  const [data, setData] = useState<ChartResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch chart data — state updates batched inside async to satisfy
  // react-hooks/set-state-in-effect (no synchronous setState in effect body).
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const r = await fetch(
          `/api/chart?ticker=${encodeURIComponent(ticker)}&timeframe=${tf}&years=${years}`,
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (!cancelled) setData(j);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [ticker, tf, years]);

  // Render chart whenever data or container changes.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !data) return;

    let chart: IChartApi | null = null;
    let candleSeries: ISeriesApi<"Candlestick"> | null = null;
    const maSeriesList: Array<ISeriesApi<"Line">> = [];

    const init = async () => {
      const lwc = await import("lightweight-charts");
      // CSS color from current document (so dark/light is respected)
      const computed = getComputedStyle(document.documentElement);
      const fg = computed.getPropertyValue("--foreground").trim() || "#111";
      const bg = computed.getPropertyValue("--background").trim() || "#fff";

      chart = lwc.createChart(el, {
        height,
        layout: { background: { color: bg }, textColor: fg },
        grid: { vertLines: { color: "rgba(127,127,127,0.1)" }, horzLines: { color: "rgba(127,127,127,0.1)" } },
        rightPriceScale: { borderColor: "rgba(127,127,127,0.2)" },
        timeScale: { borderColor: "rgba(127,127,127,0.2)", timeVisible: false },
      });
      chartRef.current = chart;

      candleSeries = chart.addSeries(lwc.CandlestickSeries, {
        upColor: "#ef4444", downColor: "#3b82f6",
        borderUpColor: "#ef4444", borderDownColor: "#3b82f6",
        wickUpColor: "#ef4444", wickDownColor: "#3b82f6",
      });
      const candleData: CandlestickData[] = data.bars.map((b) => ({
        time: b.t as Time,
        open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      candleSeries.setData(candleData);

      // Moving averages
      for (const [key, points] of Object.entries(data.mas)) {
        const color = MA_COLORS[key] ?? "#888";
        const lineSeries = chart.addSeries(lwc.LineSeries, {
          color,
          lineWidth: key === "ma_240" || key === "ma_10" ? 2 : 1,
          priceLineVisible: false,
          lastValueVisible: false,
          title: key.replace("ma_", "MA"),
        });
        const lineData: LineData[] = (points as MAPoint[]).map((p) => ({
          time: p.t as Time,
          value: p.value,
        }));
        lineSeries.setData(lineData);
        maSeriesList.push(lineSeries);
      }

      // 4-quadrant lines as price levels
      const ql = data.quarter_lines;
      if (ql && candleSeries) {
        candleSeries.createPriceLine({ price: ql.price_high, color: QUARTER_COLORS.high, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "100%" });
        candleSeries.createPriceLine({ price: ql.price_75, color: QUARTER_COLORS.p75, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "75% 안전" });
        candleSeries.createPriceLine({ price: ql.price_50, color: QUARTER_COLORS.p50, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "50%" });
        candleSeries.createPriceLine({ price: ql.price_25, color: QUARTER_COLORS.p25, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "25% 절대" });
        candleSeries.createPriceLine({ price: ql.price_low, color: QUARTER_COLORS.low, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "0%" });
      }

      // Pattern entry/stop/target lines (most recent completed only)
      const latest = data.patterns[0];
      if (latest && candleSeries) {
        if (latest.entry != null) {
          candleSeries.createPriceLine({ price: latest.entry, color: "#22c55e", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `진입 ${latest.kind}` });
        }
        if (latest.stop != null) {
          candleSeries.createPriceLine({ price: latest.stop, color: "#ef4444", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "손절" });
        }
        if (latest.target != null) {
          candleSeries.createPriceLine({ price: latest.target, color: "#0ea5e9", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "목표" });
        }
      }

      // Fit content
      chart.timeScale().fitContent();
    };

    init();

    // Resize observer for responsive width
    const resizeObserver = new ResizeObserver((entries) => {
      if (!chart || !entries[0]) return;
      const { width } = entries[0].contentRect;
      chart.applyOptions({ width });
    });
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      try { chart?.remove(); } catch { /* ignore */ }
      chartRef.current = null;
    };
  }, [data, height]);

  return (
    <div className="space-y-3" data-testid="book-chart">
      <div className="flex items-center justify-between">
        <div className="inline-flex rounded-md border border-input overflow-hidden" role="tablist">
          {(["daily", "weekly", "monthly"] as Timeframe[]).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tf === t}
              onClick={() => setTf(t)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                tf === t
                  ? "bg-foreground text-background"
                  : "bg-background hover:bg-muted text-muted-foreground"
              }`}
            >
              {t === "daily" ? "일봉" : t === "weekly" ? "주봉" : "월봉"}
            </button>
          ))}
        </div>
        {data?.patterns?.[0] && (
          <div className="text-xs text-muted-foreground">
            <span className="font-medium">{data.patterns[0].kind}</span>
            {" · "}
            <span>신뢰도 {(data.patterns[0].confidence * 100).toFixed(0)}%</span>
            {" · "}
            <span>{data.patterns[0].direction === "bullish" ? "🟢 상승" : "🔴 하락"}</span>
          </div>
        )}
      </div>
      <div className="rounded-lg border border-border overflow-hidden bg-card">
        {loading && (
          <div className="h-[480px] flex items-center justify-center text-sm text-muted-foreground">
            차트 로드 중...
          </div>
        )}
        {error && !loading && (
          <div className="h-[480px] flex items-center justify-center text-sm text-rose-500">
            차트 불러오기 실패: {error}
          </div>
        )}
        {!loading && !error && (
          <div ref={containerRef} style={{ height }} />
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {Object.entries(MA_COLORS).map(([k, c]) => (
          <span key={k} className="inline-flex items-center gap-1">
            <span style={{ width: 10, height: 2, background: c }} />
            {k.replace("ma_", "MA")}
          </span>
        ))}
      </div>
    </div>
  );
}
