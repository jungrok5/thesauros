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
import { LiveQuote } from "@/components/live-quote";
import { InvestorFlow } from "@/components/investor-flow";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
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

  const [result, watch] = await Promise.all([
    isCanonical ? getAnalysis(ticker) : Promise.resolve(null),
    isCanonical ? getWatchlistState(ticker) : Promise.resolve({ added: false, category: "observing" as const }),
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
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
          <div className="font-medium text-amber-700 dark:text-amber-300">
            {resolved?.name ?? ticker} 분석 데이터가 아직 없습니다.
          </div>
          <div className="mt-2 text-muted-foreground">
            이 종목은 다음 일일 스캔 (매일 16시 KST) 에 자동으로 분석됩니다.
            수동으로 즉시 분석하려면:
            <code className="ml-1 bg-muted px-1 rounded font-mono text-xs">
              python -m app.db.scan_daily --tickers {ticker} --years 2
            </code>
          </div>
        </div>
      ) : (
        <>
          <LiveQuote ticker={ticker} />
          <InvestorFlow ticker={ticker} />
          <div>
            <h2 className="mb-3 text-lg font-semibold tracking-tight">
              차트 + 책 신호 오버레이
            </h2>
            <BookChart ticker={ticker} timeframe="weekly" years={2} />
          </div>
          <AnalysisView result={result} />
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
