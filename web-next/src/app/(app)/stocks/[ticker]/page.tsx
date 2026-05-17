/**
 * /stocks/[ticker] — single stock detail.
 *
 * Reads the full analyze result from Supabase `analyze_results` (populated
 * daily by app.db.scan_daily). No FastAPI dependency.
 *
 * If a ticker has never been scanned, we render a "no analysis yet"
 * fallback. The daily cron will pick it up on the next run.
 */
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

interface PageProps {
  params: Promise<{ ticker: string }>;
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
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw).toUpperCase();

  const [result, watch] = await Promise.all([
    getAnalysis(ticker),
    getWatchlistState(ticker),
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
        <div className="font-mono text-lg">{ticker}</div>
        <WatchlistButton
          ticker={ticker}
          initiallyAdded={watch.added}
          initialCategory={watch.category}
        />
      </div>

      {!result ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
          <div className="font-medium text-amber-700 dark:text-amber-300">
            {ticker} 분석 데이터가 아직 없습니다.
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
