"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  LineData,
  Time,
} from "lightweight-charts";
import { Maximize2, Minimize2, X } from "lucide-react";

type Timeframe = "weekly" | "monthly";

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

// Range presets — number of weekly/monthly bars to show.
// Weekly: 13/26/52/156/all = 3M/6M/1Y/3Y/All
// Monthly: 6/12/24/60/all
const RANGE_PRESETS: Array<{
  label: string;
  weekly: number | "all";
  monthly: number | "all";
}> = [
  { label: "3M",  weekly: 13,  monthly: 3 },
  { label: "6M",  weekly: 26,  monthly: 6 },
  { label: "1Y",  weekly: 52,  monthly: 12 },
  { label: "3Y",  weekly: 156, monthly: 36 },
  { label: "All", weekly: "all", monthly: "all" },
];

interface Props {
  ticker: string;
  timeframe?: Timeframe;
  years?: number;
  height?: number;
}

export function BookChart({ ticker, timeframe: initialTf = "weekly", years = 5, height }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tf, setTf] = useState<Timeframe>(initialTf);
  const [data, setData] = useState<ChartResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeRange, setActiveRange] = useState<string>("1Y");
  const [fullscreen, setFullscreen] = useState(false);
  const [hoverInfo, setHoverInfo] = useState<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
  } | null>(null);
  // Hidden MAs — let users declutter the chart.
  const [hiddenMAs, setHiddenMAs] = useState<Set<string>>(new Set());

  // Sizing: bigger default than before (was 320/480 → now 480/640),
  // fullscreen uses ~80vh.
  const [chartHeight, setChartHeight] = useState<number>(height ?? 640);
  useEffect(() => {
    if (height && !fullscreen) return;
    const apply = () => {
      if (fullscreen) {
        setChartHeight(Math.max(window.innerHeight - 180, 400));
      } else {
        setChartHeight(window.innerWidth < 640 ? 420 : 640);
      }
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, [height, fullscreen]);

  // Body scroll lock + ESC close while fullscreen.
  useEffect(() => {
    if (!fullscreen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener("keydown", onKey);
    };
  }, [fullscreen]);

  // Fetch chart data.
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

  // Apply a range preset to the time scale by computing the visible
  // logical range from the latest N bars.
  const applyRange = useCallback((presetLabel: string) => {
    setActiveRange(presetLabel);
    const chart = chartRef.current;
    if (!chart || !data) return;
    const preset = RANGE_PRESETS.find((p) => p.label === presetLabel);
    if (!preset) return;
    const n = tf === "weekly" ? preset.weekly : preset.monthly;
    const ts = chart.timeScale();
    if (n === "all") {
      ts.fitContent();
      return;
    }
    const total = data.bars.length;
    const from = Math.max(0, total - 1 - (n as number));
    const to = total - 1;
    try {
      ts.setVisibleLogicalRange({ from, to });
    } catch {
      ts.fitContent();
    }
  }, [data, tf]);

  // Render chart whenever data or container changes.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !data) return;

    let chart: IChartApi | null = null;
    let candleSeries: ISeriesApi<"Candlestick"> | null = null;

    const init = async () => {
      const lwc = await import("lightweight-charts");
      const computed = getComputedStyle(document.documentElement);
      const fg = computed.getPropertyValue("--foreground").trim() || "#111";
      const bg = computed.getPropertyValue("--background").trim() || "#fff";

      chart = lwc.createChart(el, {
        height: chartHeight,
        layout: { background: { color: bg }, textColor: fg },
        grid: {
          vertLines: { color: "rgba(127,127,127,0.1)" },
          horzLines: { color: "rgba(127,127,127,0.1)" },
        },
        rightPriceScale: {
          borderColor: "rgba(127,127,127,0.2)",
          // Leave the bottom 22% of the chart for the volume histogram
          // so it never overlaps with candles. Book룰 — 거래량은
          // first-class 신호 (case 1~12)이므로 캔들과 같이 봐야 한다.
          scaleMargins: { top: 0.08, bottom: 0.22 },
        },
        timeScale: {
          borderColor: "rgba(127,127,127,0.2)",
          timeVisible: false,
        },
        crosshair: {
          mode: 0,   // Magnet mode — snaps to bars (book: 종가매매)
        },
      });
      chartRef.current = chart;

      candleSeries = chart.addSeries(lwc.CandlestickSeries, {
        // Korean / book convention: 상승=빨강, 하락=파랑. Keeping it.
        upColor: "#ef4444", downColor: "#3b82f6",
        borderUpColor: "#ef4444", borderDownColor: "#3b82f6",
        wickUpColor: "#ef4444", wickDownColor: "#3b82f6",
      });
      const candleData: CandlestickData[] = data.bars.map((b) => ({
        time: b.t as Time,
        open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      candleSeries.setData(candleData);

      // Volume histogram (separate price scale, anchored to bottom 22 %).
      // Color matches the candle direction so a glance shows "buying vs
      // selling 거래량" — central to book's 11+1 case analysis (p364).
      const volumeSeries = chart.addSeries(lwc.HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
        lastValueVisible: false,
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.78, bottom: 0 },   // bottom 22 % strip
        borderColor: "rgba(127,127,127,0.2)",
      });
      const volumeData: HistogramData[] = data.bars.map((b) => ({
        time: b.t as Time,
        value: b.volume,
        color: b.close >= b.open
          ? "rgba(239, 68, 68, 0.55)"   // 양봉 빨강 (60% alpha)
          : "rgba(59, 130, 246, 0.55)", // 음봉 파랑
      }));
      volumeSeries.setData(volumeData);

      // 20-bar volume MA — book "거래량 평균 대비" anchor for cases 3/9
      // (3배 이상 폭증 vs 평균 미만 감소).
      const N_AVG = 20;
      const volMA: LineData[] = [];
      for (let i = N_AVG - 1; i < data.bars.length; i++) {
        let sum = 0;
        for (let j = i - N_AVG + 1; j <= i; j++) sum += data.bars[j].volume;
        volMA.push({
          time: data.bars[i].t as Time,
          value: sum / N_AVG,
        });
      }
      if (volMA.length > 0) {
        const volMaSeries = chart.addSeries(lwc.LineSeries, {
          color: "#f59e0b",                  // amber — 평균 거래량 라인
          lineWidth: 1,
          priceScaleId: "volume",
          lastValueVisible: false,
          priceLineVisible: false,
          title: "20MA Vol",
        });
        volMaSeries.setData(volMA);
      }

      // Moving averages — skip hidden ones for declutter.
      for (const [key, points] of Object.entries(data.mas)) {
        if (hiddenMAs.has(key)) continue;
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
      }

      // 4-quadrant lines as price levels (when catalyst exists).
      const ql = data.quarter_lines;
      if (ql && candleSeries) {
        candleSeries.createPriceLine({ price: ql.price_high, color: QUARTER_COLORS.high, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "100%" });
        candleSeries.createPriceLine({ price: ql.price_75,   color: QUARTER_COLORS.p75,  lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "75% 안전" });
        candleSeries.createPriceLine({ price: ql.price_50,   color: QUARTER_COLORS.p50,  lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "50%" });
        candleSeries.createPriceLine({ price: ql.price_25,   color: QUARTER_COLORS.p25,  lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "25% 절대" });
        candleSeries.createPriceLine({ price: ql.price_low,  color: QUARTER_COLORS.low,  lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "0%" });
      }

      // Pattern entry/stop/target lines (most recent completed only).
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

      // Crosshair → live OHLC tooltip (top-left overlay).
      chart.subscribeCrosshairMove((param) => {
        if (!candleSeries || !param.time || !param.seriesData.has(candleSeries)) {
          setHoverInfo(null);
          return;
        }
        const bar = param.seriesData.get(candleSeries) as
          | CandlestickData | undefined;
        if (!bar) {
          setHoverInfo(null);
          return;
        }
        const ts = typeof param.time === "number"
          ? param.time
          : (param.time as { timestamp?: number }).timestamp ?? 0;
        const d = new Date((ts as number) * 1000);
        // Look up volume by matching the bar timestamp (lightweight-charts
        // doesn't surface other series' data through this callback).
        const matched = data.bars.find((b) => b.t === ts);
        setHoverInfo({
          date: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
          open: bar.open, high: bar.high, low: bar.low, close: bar.close,
          volume: matched?.volume,
        });
      });

      // Default visible range = 1Y from the latest bar.
      const preset = RANGE_PRESETS.find((p) => p.label === activeRange);
      if (preset) {
        const n = tf === "weekly" ? preset.weekly : preset.monthly;
        if (n !== "all") {
          const total = data.bars.length;
          const from = Math.max(0, total - 1 - (n as number));
          const to = total - 1;
          try {
            chart.timeScale().setVisibleLogicalRange({ from, to });
          } catch {
            chart.timeScale().fitContent();
          }
        } else {
          chart.timeScale().fitContent();
        }
      }
    };

    init();

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
    // hiddenMAs intentionally a dep so toggle re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, chartHeight, hiddenMAs]);

  const toggleMA = (key: string) => {
    setHiddenMAs((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const latestPattern = useMemo(() => data?.patterns?.[0], [data]);

  const content = (
    <div className="space-y-3" data-testid="book-chart">
      {/* Top bar: timeframe + range presets + fullscreen + pattern badge */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded-md border border-input overflow-hidden" role="tablist" aria-label="시간프레임">
            {(["weekly", "monthly"] as Timeframe[]).map((t) => (
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
                {t === "weekly" ? "주봉" : "월봉"}
              </button>
            ))}
          </div>
          <div className="inline-flex rounded-md border border-input overflow-hidden" role="tablist" aria-label="기간">
            {RANGE_PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                role="tab"
                aria-selected={activeRange === p.label}
                onClick={() => applyRange(p.label)}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  activeRange === p.label
                    ? "bg-foreground text-background"
                    : "bg-background hover:bg-muted text-muted-foreground"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setFullscreen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md border border-input px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={fullscreen ? "전체화면 종료" : "전체화면"}
          >
            {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">{fullscreen ? "원래 크기" : "크게 보기"}</span>
          </button>
        </div>
        {latestPattern && (
          <div className="text-xs text-muted-foreground">
            <span className="font-medium">{latestPattern.kind}</span>
            {" · "}
            <span>신뢰도 {(latestPattern.confidence * 100).toFixed(0)}%</span>
            {" · "}
            <span>{latestPattern.direction === "bullish" ? "🟢 상승" : "🔴 하락"}</span>
          </div>
        )}
      </div>

      {/* Chart container with OHLC tooltip overlay */}
      <div className="rounded-lg border border-border overflow-hidden bg-card relative">
        {loading && (
          <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height: chartHeight }}>
            차트 로드 중...
          </div>
        )}
        {error && !loading && (
          <div className="flex items-center justify-center text-sm text-rose-500" style={{ height: chartHeight }}>
            차트 불러오기 실패: {error}
          </div>
        )}
        {!loading && !error && (
          <>
            <div ref={containerRef} style={{ height: chartHeight }} />
            {hoverInfo && (
              <div className="absolute top-2 left-2 pointer-events-none rounded-md bg-card/95 border border-border px-2 py-1 text-[11px] font-mono shadow-sm space-y-0.5">
                <div className="text-muted-foreground">{hoverInfo.date}</div>
                <div>
                  <span className="text-muted-foreground">O </span>
                  {hoverInfo.open.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  {" · "}
                  <span className="text-muted-foreground">H </span>
                  {hoverInfo.high.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
                <div>
                  <span className="text-muted-foreground">L </span>
                  {hoverInfo.low.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  {" · "}
                  <span className="text-muted-foreground">C </span>
                  {hoverInfo.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
                {hoverInfo.volume != null && (
                  <div>
                    <span className="text-muted-foreground">V </span>
                    {hoverInfo.volume >= 1e6
                      ? `${(hoverInfo.volume / 1e6).toFixed(1)}M`
                      : hoverInfo.volume.toLocaleString()}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* MA legend — click to toggle visibility */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {Object.entries(MA_COLORS).map(([k, c]) => {
          const hidden = hiddenMAs.has(k);
          return (
            <button
              key={k}
              type="button"
              onClick={() => toggleMA(k)}
              className={`inline-flex items-center gap-1.5 rounded-md border border-input px-2 py-1 transition-opacity ${
                hidden ? "opacity-40" : ""
              }`}
              aria-pressed={!hidden}
              title={hidden ? "보기" : "숨기기"}
            >
              <span style={{ width: 12, height: 2, background: c }} />
              {k.replace("ma_", "MA")}
            </button>
          );
        })}
        <span className="inline-flex items-center gap-1 rounded-md border border-input px-2 py-1">
          <span style={{ width: 12, height: 6, background: "#ef4444aa" }} />/
          <span style={{ width: 12, height: 6, background: "#3b82f6aa" }} />
          거래량 (양/음봉)
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-input px-2 py-1">
          <span style={{ width: 12, height: 2, background: "#f59e0b" }} />
          20MA Vol (책: 평균 대비 3배+ = 폭증)
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground/70 leading-tight">
          💡 마우스 휠 = 확대·축소 · 드래그 = 좌우 이동 · 더블클릭 = 자동 맞춤
          <br />
          📌 분석 결론은 위쪽 정리표를 참고 — 이 차트는 정리표의 결론을 시각적으로 검증하는 용도
        </span>
      </div>
    </div>
  );

  if (fullscreen) {
    return (
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${ticker} 차트 전체화면`}
        className="fixed inset-0 z-50 bg-background flex flex-col"
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-mono font-medium">{ticker}</span>
            <span className="text-muted-foreground">· {tf === "weekly" ? "주봉" : "월봉"}</span>
          </div>
          <button
            type="button"
            onClick={() => setFullscreen(false)}
            className="rounded-md border border-input p-1.5 hover:bg-muted"
            aria-label="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4 max-w-7xl mx-auto w-full">
          {content}
        </div>
      </div>
    );
  }

  return content;
}
