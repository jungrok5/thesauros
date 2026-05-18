/**
 * GET /api/chart?ticker=...&timeframe=weekly|monthly&years=N
 *
 * Reads pre-resampled bars from Supabase `bars` (granularity 'W' or 'M').
 * The Phase 2 weekly-pivot dropped daily storage entirely — book strategy
 * is swing trading and the engine's primary signals are 월봉 240MA +
 * 월봉/주봉 10MA, so daily storage added cost without analysis value.
 *
 * Response shape (unchanged so BookChart needs no edits):
 *   { ticker, timeframe, bars, mas, patterns, quarter_lines, last_candle }
 *
 * For brand-new US tickers the user views before the next bar-ingest
 * cron has run, we fall back to live Naver (same source the cron uses).
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;
const TIMEFRAME_RE = /^(weekly|monthly)$/;

type Bar = {
  t: number;
  open: number; high: number; low: number; close: number; volume: number;
};
type MAPoint = { t: number; value: number };

interface AnalysisFullResult {
  patterns?: unknown[];
  quarter_lines?: unknown;
  last_candle?: unknown;
}

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = new URL(req.url);
  const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
  const timeframe = (url.searchParams.get("timeframe") ?? "weekly") as
    | "weekly"
    | "monthly";
  const yearsStr = url.searchParams.get("years") ?? "5";

  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!TIMEFRAME_RE.test(timeframe)) {
    return NextResponse.json(
      { error: "invalid timeframe (weekly|monthly only)" },
      { status: 400 },
    );
  }
  const years = Number(yearsStr);
  if (!Number.isInteger(years) || years < 1 || years > 20) {
    return NextResponse.json({ error: "invalid years" }, { status: 400 });
  }

  const granularity = timeframe === "weekly" ? "W" : "M";
  const sb = getServerClient();

  const { data: rows, error } = await sb
    .from("bars")
    .select("bar_date, open, high, low, close, volume")
    .eq("ticker", ticker)
    .eq("granularity", granularity)
    .order("bar_date", { ascending: true });

  if (error) {
    console.error("bars read:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  let bars: ResampledBar[];
  let liveFallback = false;

  if (!rows || rows.length === 0) {
    // Fallback to live Naver — same source the cron uses, so a user
    // viewing a brand-new ticker right after watchlisting still gets
    // a chart while the workflow_dispatch is still running.
    const live = await fetchNaverBars(ticker, granularity);
    if (!live.length) {
      return NextResponse.json({ error: "no data", ticker }, { status: 404 });
    }
    bars = live;
    liveFallback = true;
  } else {
    bars = rows.map((r) => ({
      date: new Date(r.bar_date),
      open: Number(r.open), high: Number(r.high), low: Number(r.low),
      close: Number(r.close), volume: Number(r.volume) || 0,
    }));
  }

  // MAs over full series for warmup, then slice to visible window.
  const mas = computeMAs(bars, [10, 20, 60, 120, 240]);
  const cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - years);
  const visibleStart = bars.findIndex((b) => b.date >= cutoff);
  const visible = visibleStart < 0 ? bars : bars.slice(visibleStart);
  const startIdx = visibleStart < 0 ? 0 : visibleStart;

  const out: Bar[] = visible.map((b) => ({
    t: Math.floor(b.date.getTime() / 1000),
    open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
  }));

  const slicedMas: Record<string, MAPoint[]> = {};
  for (const [key, full] of Object.entries(mas)) {
    slicedMas[key] = full
      .slice(startIdx)
      .filter((p) => p.value !== null)
      .map((p) => ({
        t: Math.floor(p.date.getTime() / 1000),
        value: p.value as number,
      }));
  }

  // Patterns + quarter_lines + last_candle from analyze_results (single
  // shared analysis per ticker, displayed on both weekly and monthly).
  const { data: ar } = await sb
    .from("analyze_results")
    .select("result")
    .eq("ticker", ticker)
    .maybeSingle();
  const result = (ar?.result ?? {}) as AnalysisFullResult;
  const patterns = (result.patterns ?? []) as unknown[];
  const completedPatterns = patterns.filter(
    (p): p is { completed?: boolean } => typeof p === "object" && p !== null,
  ).filter((p) => p.completed !== false);

  return NextResponse.json({
    ticker,
    timeframe,
    bars: out,
    mas: slicedMas,
    patterns: liveFallback ? [] : completedPatterns,
    quarter_lines: liveFallback ? null : (result.quarter_lines ?? null),
    last_candle: liveFallback ? null : (result.last_candle ?? null),
    source: liveFallback ? "naver_live" : "supabase_cron",
  });
}

// ---- helpers ----------------------------------------------------------

type ResampledBar = {
  date: Date; open: number; high: number; low: number;
  close: number; volume: number;
};

function computeMAs(
  bars: ResampledBar[],
  windows: number[],
): Record<string, { date: Date; value: number | null }[]> {
  const out: Record<string, { date: Date; value: number | null }[]> = {};
  for (const w of windows) {
    if (bars.length < w) {
      out[`ma_${w}`] = bars.map((b) => ({ date: b.date, value: null }));
      continue;
    }
    const closes = bars.map((b) => b.close);
    let sum = 0;
    const series: { date: Date; value: number | null }[] = [];
    for (let i = 0; i < bars.length; i++) {
      sum += closes[i];
      if (i >= w) sum -= closes[i - w];
      series.push({
        date: bars[i].date,
        value: i >= w - 1 ? sum / w : null,
      });
    }
    out[`ma_${w}`] = series;
  }
  return out;
}

/**
 * Live Naver fallback for brand-new tickers. Same endpoint app/data/
 * naver_bars.py uses on the Python side; tries .O, .K, .A suffixes.
 * Cached at the Next.js layer for 1h per (ticker, granularity) URL.
 */
async function fetchNaverBars(
  ticker: string, granularity: "W" | "M",
): Promise<ResampledBar[]> {
  const periodType = granularity === "W" ? "weekCandle" : "monthCandle";
  const endDate = new Date(Date.now() + 86_400_000);
  const startDate = new Date(Date.now() - 365 * 10 * 86_400_000);
  const fmt = (d: Date) =>
    d.toISOString().slice(0, 19).replace(/[-:T]/g, "");

  for (const suffix of [".O", ".K", ".A"]) {
    const symbol = ticker + suffix;
    const qs = new URLSearchParams({
      startDateTime: fmt(startDate),
      endDateTime: fmt(endDate),
      periodType,
    });
    try {
      const res = await fetch(
        `https://api.stock.naver.com/chart/foreign/item/${symbol}?${qs}`,
        {
          headers: {
            "User-Agent": "Mozilla/5.0",
            Referer: "https://m.stock.naver.com/",
            Accept: "application/json",
          },
          next: { revalidate: 3600 },
        },
      );
      if (!res.ok) continue;
      const json = await res.json();
      const infos = (json?.priceInfos ?? []) as Array<{
        localDate: string;
        openPrice: number; highPrice: number; lowPrice: number;
        closePrice: number; accumulatedTradingVolume: number;
      }>;
      if (!infos.length) continue;
      return infos.map((p) => ({
        date: new Date(
          `${p.localDate.slice(0, 4)}-${p.localDate.slice(4, 6)}-${p.localDate.slice(6, 8)}T00:00:00Z`,
        ),
        open: Number(p.openPrice), high: Number(p.highPrice),
        low: Number(p.lowPrice), close: Number(p.closePrice),
        volume: Number(p.accumulatedTradingVolume) || 0,
      }));
    } catch (e) {
      console.warn("naver fetch %s/%s: %s", symbol, periodType, e);
    }
  }
  return [];
}
