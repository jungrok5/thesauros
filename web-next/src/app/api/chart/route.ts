/**
 * GET /api/chart?ticker=...&timeframe=daily|weekly|monthly&years=N
 *
 * Computes the chart payload ON DEMAND from Supabase `bars_daily`:
 *   - bars: OHLCV resampled to the requested timeframe
 *   - mas:  10/20/60/120/240 moving averages via SQL window functions
 *   - patterns / quarter_lines / last_candle: pulled from
 *     `analyze_results.result` (computed by the daily scan cron)
 *
 * This replaces the `chart_data` precomputed cache, which was using up
 * ~200MB of Supabase free-tier storage for marginal speed gain.
 *
 * Response shape (unchanged so BookChart needs no edits):
 *   { ticker, timeframe, bars, mas, patterns, quarter_lines, last_candle }
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const TICKER_RE = /^[A-Z0-9._-]{1,16}$/i;
const TIMEFRAME_RE = /^(daily|weekly|monthly)$/;

type Bar = {
  t: number;          // unix seconds
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
  const timeframe = url.searchParams.get("timeframe") ?? "weekly";
  const yearsStr = url.searchParams.get("years") ?? "2";

  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 });
  }
  if (!TIMEFRAME_RE.test(timeframe)) {
    return NextResponse.json({ error: "invalid timeframe" }, { status: 400 });
  }
  const years = Number(yearsStr);
  if (!Number.isInteger(years) || years < 1 || years > 20) {
    return NextResponse.json({ error: "invalid years" }, { status: 400 });
  }

  const sb = getServerClient();

  // 1) Pull all daily bars for this ticker. We need full history (not just
  //    `years`) so MAs computed with rolling windows have proper warmup.
  const { data: rows, error } = await sb
    .from("bars_daily")
    .select("bar_date, open, high, low, close, volume")
    .eq("ticker", ticker)
    .order("bar_date", { ascending: true });

  if (error) {
    console.error("bars_daily read:", error.message);
    return NextResponse.json({ error: "db error" }, { status: 500 });
  }

  let daily: DailyBar[];
  let liveFallback = false;
  if (!rows || rows.length === 0) {
    // No bars in DB — try a live yfinance fetch. This is the path for
    // US tickers not watchlisted (cron doesn't scan them by default).
    // KR tickers should always be in DB so an empty result means an
    // invalid ticker or fresh listing not yet picked up by the weekly
    // tickers-refresh cron.
    const live = await fetchYahooBars(ticker, years);
    if (!live.length) {
      return NextResponse.json({ error: "no data", ticker }, { status: 404 });
    }
    daily = live;
    liveFallback = true;
  } else {
    daily = rows.map((r) => ({
      date: new Date(r.bar_date),
      open: Number(r.open), high: Number(r.high), low: Number(r.low),
      close: Number(r.close), volume: Number(r.volume) || 0,
    }));
  }
  // Skip resample for daily timeframe (identity).
  const resampled: DailyBar[] = resample(daily, timeframe as "daily" | "weekly" | "monthly");

  // 3) Compute MAs over the FULL resampled series so warmup is honored,
  //    then slice the visible window.
  const mas = computeMAs(resampled, [10, 20, 60, 120, 240]);

  const cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - years);
  const visibleStart = resampled.findIndex((b) => b.date >= cutoff);
  const visible = visibleStart < 0 ? resampled : resampled.slice(visibleStart);
  const startIdx = visibleStart < 0 ? 0 : visibleStart;

  const bars: Bar[] = visible.map((b) => ({
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

  // 4) Patterns + quarter_lines + last_candle from analyze_results (daily-based;
  //    a single shared analysis per ticker, displayed on every timeframe).
  const { data: ar } = await sb
    .from("analyze_results")
    .select("result")
    .eq("ticker", ticker)
    .maybeSingle();
  const result = (ar?.result ?? {}) as AnalysisFullResult;
  const patterns = (result.patterns ?? []) as unknown[];
  // analyze_results.result.patterns includes both completed + in-progress;
  // chart prefers completed-only ones (consistent with prior behavior).
  const completedPatterns = patterns.filter(
    (p): p is { completed?: boolean } => typeof p === "object" && p !== null,
  ).filter((p) => p.completed !== false);

  return NextResponse.json({
    ticker,
    timeframe,
    bars,
    mas: slicedMas,
    // Live-fallback path has no analyzer output — only chart + MAs.
    patterns: liveFallback ? [] : completedPatterns,
    quarter_lines: liveFallback ? null : (result.quarter_lines ?? null),
    last_candle: liveFallback ? null : (result.last_candle ?? null),
    source: liveFallback ? "yahoo_live" : "supabase_cron",
  });
}

// ---- helpers ----------------------------------------------------------

type DailyBar = {
  date: Date; open: number; high: number; low: number; close: number; volume: number;
};

function resample(daily: DailyBar[], tf: "daily" | "weekly" | "monthly"): DailyBar[] {
  if (tf === "daily") return daily;
  const out: DailyBar[] = [];
  let bucket: DailyBar[] = [];
  const key = (d: Date) => {
    if (tf === "weekly") {
      // ISO week: Monday-anchored
      const tmp = new Date(d);
      const day = (tmp.getDay() + 6) % 7;   // Mon=0..Sun=6
      tmp.setDate(tmp.getDate() - day);
      tmp.setHours(0, 0, 0, 0);
      return tmp.getTime();
    }
    return new Date(d.getFullYear(), d.getMonth(), 1).getTime();
  };
  let curKey: number | null = null;
  for (const b of daily) {
    const k = key(b.date);
    if (curKey === null) curKey = k;
    if (k !== curKey) {
      if (bucket.length > 0) out.push(closeBucket(bucket, tf));
      bucket = [];
      curKey = k;
    }
    bucket.push(b);
  }
  if (bucket.length > 0) out.push(closeBucket(bucket, tf));
  return out;
}

function closeBucket(bucket: DailyBar[], tf: "weekly" | "monthly"): DailyBar {
  const open = bucket[0].open;
  const close = bucket[bucket.length - 1].close;
  let high = bucket[0].high, low = bucket[0].low, volume = 0;
  for (const b of bucket) {
    if (b.high > high) high = b.high;
    if (b.low < low) low = b.low;
    volume += b.volume;
  }
  // anchor date: bucket start
  const anchor = tf === "weekly" ? bucket[0].date : bucket[0].date;
  return { date: anchor, open, high, low, close, volume };
}

function computeMAs(
  bars: DailyBar[],
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
 * Live fallback for tickers not yet ingested into bars_daily. Used by US
 * names the user searched without watchlisting — the daily cron only
 * ingests KR + watchlisted US. Yahoo v8 chart returns full history with
 * one HTTP call. Cached per ticker for 1 day via Next.js `revalidate`.
 */
async function fetchYahooBars(ticker: string, years: number): Promise<DailyBar[]> {
  const range = years >= 5 ? "5y" : years >= 2 ? "5y" : "2y";
  const url =
    "https://query1.finance.yahoo.com/v8/finance/chart/" +
    encodeURIComponent(ticker) +
    `?interval=1d&range=${range}`;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Accept: "application/json,*/*;q=0.1",
      },
      // Cache for 24h per (ticker, timeframe) URL.
      next: { revalidate: 86400 },
    });
    if (!res.ok) return [];
    const json = await res.json();
    const r = json?.chart?.result?.[0];
    if (!r) return [];
    const ts: number[] = r.timestamp ?? [];
    const q = r.indicators?.quote?.[0] ?? {};
    const opens: (number | null)[] = q.open ?? [];
    const highs: (number | null)[] = q.high ?? [];
    const lows: (number | null)[] = q.low ?? [];
    const closes: (number | null)[] = q.close ?? [];
    const vols: (number | null)[] = q.volume ?? [];
    const out: DailyBar[] = [];
    for (let i = 0; i < ts.length; i++) {
      const c = closes[i];
      if (c == null) continue;   // skip gaps
      out.push({
        date: new Date(ts[i] * 1000),
        open: opens[i] ?? c,
        high: highs[i] ?? c,
        low: lows[i] ?? c,
        close: c,
        volume: vols[i] ?? 0,
      });
    }
    return out;
  } catch (e) {
    console.error("yahoo chart fallback:", e);
    return [];
  }
}
