/**
 * /stocks/[ticker] — single stock detail.
 *
 * Reads the full analyze result from Supabase `analyze_results` (populated
 * daily by app.db.scan_daily). No FastAPI dependency.
 *
 * If a ticker has never been scanned, we render a "no analysis yet"
 * fallback. The daily cron will pick it up on the next run.
 *
 * URL segment resolution:
 *   - "AAPL"        → tickers.ticker exact match
 *   - "005930"      → fall back to "005930.KS" via `or()` on ticker
 *   - "현대차"      → look up by name (ilike), redirect to canonical ticker
 *   - "삼성전자"    → ditto
 *
 * Anything not resolvable still renders the page, just without name.
 */
import { redirect } from "next/navigation";
import { TickerSearch } from "@/components/ticker-search";
import { AnalysisView } from "@/components/analysis-view";
import { WatchlistButton } from "@/components/watchlist-button";
import { StockContextTabs } from "@/components/stock-context-tabs";
import { BookChart } from "@/components/book-chart";
import { LastClose } from "@/components/last-close";
import { MarketHoursNotice } from "@/components/market-hours-notice";
import { InvestorFlow } from "@/components/investor-flow";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { ensureTickerInMaster } from "@/lib/ensure-ticker";
import { searchNaverStocks } from "@/lib/naver-search";
import type { AnalysisResult } from "@/lib/types/analysis";

export const dynamic = "force-dynamic";

const CANONICAL_TICKER_RE = /^[A-Z0-9]{1,12}(\.[A-Z]{1,4})?$/;

interface PageProps {
  params: Promise<{ ticker: string }>;
}

type TickerInfo = { ticker: string; name: string | null; market: string | null };

/**
 * Look up the canonical ticker + Korean name for whatever the user typed
 * into the URL. Returns null if nothing matched.
 */
async function resolveTicker(raw: string): Promise<TickerInfo | null> {
  const sb = getServerClient();
  const upper = raw.toUpperCase();

  // 1) Exact match on ticker (covers "AAPL", "005930.KS").
  {
    const { data } = await sb
      .from("tickers")
      .select("ticker, name, market")
      .eq("ticker", upper)
      .maybeSingle();
    if (data) return data as TickerInfo;
  }

  // 2) 6-digit Korean code without suffix → try both .KS and .KQ.
  if (/^\d{6}$/.test(raw)) {
    const { data } = await sb
      .from("tickers")
      .select("ticker, name, market")
      .in("ticker", [`${raw}.KS`, `${raw}.KQ`])
      .limit(1)
      .maybeSingle();
    if (data) return data as TickerInfo;
  }

  // 3) Exact Korean-name match.
  {
    const { data } = await sb
      .from("tickers")
      .select("ticker, name, market")
      .ilike("name", raw)
      .eq("is_active", true)
      .limit(1)
      .maybeSingle();
    if (data) return data as TickerInfo;
  }

  // 4) Fuzzy name match (one substring hit wins).
  {
    const { data } = await sb
      .from("tickers")
      .select("ticker, name, market")
      .ilike("name", `%${raw}%`)
      .eq("is_active", true)
      .limit(1)
      .maybeSingle();
    if (data) return data as TickerInfo;
  }

  // 5) Naver integrated search fallback — handles Korean brand names
  //    ("샌디스크"→SNDK, "애플"→AAPL) and English consumer brands
  //    ("GOOGLE"→GOOGL) that aren't substrings of our canonical
  //    corporate names. Auto-seeds the resolved ticker into `tickers`
  //    so subsequent watchlist + chart calls work. Wrapped in
  //    try/catch — Naver outages must not crash the page.
  try {
    const hits = await searchNaverStocks(raw, 1);
    if (hits.length > 0) {
      const h = hits[0];
      const ensured = await ensureTickerInMaster(h.ticker);
      if (ensured.ok) {
        return {
          ticker: ensured.ticker,
          name: ensured.name ?? h.name,
          market: ensured.market ?? h.market,
        };
      }
    }
  } catch (e) {
    console.error("resolveTicker naver fallback:", e);
  }

  return null;
}

async function getWatchlistState(
  ticker: string,
): Promise<{ added: boolean; category: "observing" | "holding" }> {
  const session = await auth();
  if (!session?.user?.email) return { added: false, category: "observing" };
  try {
    const userId = await ensureUserId(
      session.user.email.toLowerCase(),
      session.user.name ?? null,
    );
    const sb = getServerClient();
    const { data } = await sb
      .from("watchlist")
      .select("category")
      .eq("user_id", userId)
      .eq("ticker", ticker)
      .maybeSingle();
    if (data?.category) {
      // Touch the TTL anchor — retention purges observing rows that
      // haven't been touched in 90 days (see app/db/retention.py).
      // Fire-and-forget so a slow UPDATE never delays the page render.
      sb.from("watchlist")
        .update({ last_accessed_at: new Date().toISOString() })
        .eq("user_id", userId)
        .eq("ticker", ticker)
        .then(({ error }) => {
          if (error) console.error("watchlist touch:", error.message);
        });
      return { added: true, category: data.category as "observing" | "holding" };
    }
  } catch {
    /* swallow — show un-added state */
  }
  return { added: false, category: "observing" };
}

async function getAnalysis(ticker: string): Promise<AnalysisResult | null> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("analyze_results")
    .select("result")
    .eq("ticker", ticker)
    .maybeSingle();
  if (error) {
    console.error("analyze_results read:", error.message);
    return null;
  }
  return (data?.result as AnalysisResult | undefined) ?? null;
}

async function getFlowSummary(ticker: string): Promise<
  { foreignNet: number; institutionNet: number; latestDay: string | null } | null
> {
  const sb = getServerClient();
  const since = new Date(Date.now() - 7 * 86_400_000).toISOString().slice(0, 10);
  const { data, error } = await sb
    .from("investor_flow")
    .select("day, foreign_net, institution_net")
    .eq("ticker", ticker)
    .gte("day", since)
    .order("day", { ascending: false });
  if (error || !data || data.length === 0) return null;
  let f = 0, i = 0;
  for (const r of data) {
    f += Number(r.foreign_net) || 0;
    i += Number(r.institution_net) || 0;
  }
  return { foreignNet: f, institutionNet: i, latestDay: data[0].day };
}

async function getSparklineCloses(ticker: string): Promise<number[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("bars")
    .select("close")
    .eq("ticker", ticker)
    .eq("granularity", "W")
    .order("bar_date", { ascending: false })
    .limit(60);
  if (error || !data) return [];
  return data
    .map((r) => Number(r.close))
    .filter((n) => Number.isFinite(n))
    .reverse();
}

export default async function StockDetailPage({ params }: PageProps) {
  const { ticker: rawSegment } = await params;
  const raw = decodeURIComponent(rawSegment);

  const resolved = await resolveTicker(raw);

  // If the URL segment is not the canonical ticker, redirect so the page
  // works with a watchlist-friendly ticker (Korean names would 400 the
  // watchlist API).
  if (resolved && resolved.ticker !== raw.toUpperCase()) {
    redirect(`/stocks/${encodeURIComponent(resolved.ticker)}`);
  }

  // Tolerate the no-match case: still render the search bar + a friendly
  // message, and refuse to render the watchlist buttons (no canonical
  // ticker to bind to).
  const ticker = resolved?.ticker ?? raw.toUpperCase();
  const isCanonical = CANONICAL_TICKER_RE.test(ticker);

  const [result, watch, flow, sparkCloses] = await Promise.all([
    isCanonical ? getAnalysis(ticker) : Promise.resolve(null),
    isCanonical ? getWatchlistState(ticker) : Promise.resolve({ added: false, category: "observing" as const }),
    isCanonical ? getFlowSummary(ticker) : Promise.resolve(null),
    isCanonical ? getSparklineCloses(ticker) : Promise.resolve<number[]>([]),
  ]);

  return (
    <div className="space-y-6 max-w-6xl">
      <Link
        href="/stocks"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        다른 종목 검색
      </Link>

      <div className="rounded-lg border border-border bg-card p-4">
        <TickerSearch />
      </div>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="font-mono text-lg">{ticker}</span>
          {resolved?.name && (
            <span className="text-lg font-medium">{resolved.name}</span>
          )}
          {resolved?.market && (
            <span className="text-xs text-muted-foreground border border-border rounded px-1.5 py-0.5">
              {resolved.market}
            </span>
          )}
        </div>
        {isCanonical && (
          <WatchlistButton
            ticker={ticker}
            initiallyAdded={watch.added}
            initialCategory={watch.category}
          />
        )}
      </div>

      {!isCanonical ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm">
          <div className="font-medium text-rose-700 dark:text-rose-300">
            &quot;{raw}&quot; 에 해당하는 종목을 찾지 못했습니다.
          </div>
          <div className="mt-2 text-muted-foreground">
            한글 종목명, 영문 티커(AAPL), 한국 6자리 코드(005930) 모두 검색 가능합니다.
            오타가 아닌지 확인하거나 위 검색창에서 자동완성 후보를 선택해 보세요.
          </div>
        </div>
      ) : !result ? (
        watch.added ? (
          // User just added this ticker to their watchlist — the POST
          // handler fired `dispatchAnalyzeTicker` which kicks off an
          // analyze-ticker.yml workflow on GitHub Actions. Typical
          // wall-clock to results landing in `analyze_results` is 2-3
          // min (pip install → scan_daily → telegram_worker).
          <div className="rounded-lg border border-sky-500/40 bg-sky-500/5 p-4 text-sm">
            <div className="font-medium text-sky-700 dark:text-sky-300">
              🔄 분석 중입니다 (최대 3분)
            </div>
            <div className="mt-2 text-muted-foreground">
              {resolved?.name ?? ticker} 을(를) 관심 종목에 추가하면서
              즉시 분석이 시작되었습니다. 잠시 후 페이지를 새로고침하면
              17 패턴 + 4 등분선 결과를 볼 수 있습니다.
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
            <div className="font-medium text-amber-700 dark:text-amber-300">
              {resolved?.name ?? ticker} 분석 데이터가 아직 없습니다.
            </div>
            <div className="mt-2 text-muted-foreground">
              관심 종목에 추가하면 즉시 분석이 시작됩니다 (~3분).
              혹은 다음 주간 스캔 (매주 금요일 17시 KST) 에 자동으로 분석됩니다.
            </div>
          </div>
        )
      ) : (
        <>
          <MarketHoursNotice />
          <LastClose ticker={ticker} />
          <InvestorFlow ticker={ticker} />
          <div>
            <h2 className="mb-3 text-lg font-semibold tracking-tight">
              차트 + 책 신호 오버레이
            </h2>
            <BookChart ticker={ticker} timeframe="weekly" years={2} />
          </div>
          <AnalysisView result={result} flow={flow} sparklineCloses={sparkCloses} />
          <div className="mt-8">
            <h2 className="mb-3 text-lg font-semibold tracking-tight">
              종목 정보
            </h2>
            <StockContextTabs ticker={ticker} />
          </div>
        </>
      )}
    </div>
  );
}
