import { api } from "@/lib/api";
import { TickerSearch } from "@/components/ticker-search";
import { AnalysisView } from "@/components/analysis-view";
import { WatchlistButton } from "@/components/watchlist-button";
import { StockContextTabs } from "@/components/stock-context-tabs";
import { BookChart } from "@/components/book-chart";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";

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

export default async function StockDetailPage({ params }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw).toUpperCase();

  const [result, watch] = await Promise.all([
    api.analyze(ticker, 5).catch((e) => ({ _error: String(e) })),
    getWatchlistState(ticker),
  ]);
  const error =
    "_error" in (result as object)
      ? (result as { _error: string })._error
      : null;
  const ok = !error ? (result as Awaited<ReturnType<typeof api.analyze>>) : null;

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

      {error || !ok ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm">
          <div className="font-medium text-rose-700 dark:text-rose-300">
            {ticker} 분석에 실패했습니다.
          </div>
          <div className="mt-2 font-mono text-xs text-rose-700/80 dark:text-rose-200/80">
            {error ?? "no result"}
          </div>
          <div className="mt-3 text-muted-foreground">
            가능한 원인: 잘못된 티커 / 가격 데이터 없음 (DB 미적재) / 백엔드
            미실행
          </div>
        </div>
      ) : (
        <>
          <div>
            <h2 className="mb-3 text-lg font-semibold tracking-tight">차트 + 책 신호 오버레이</h2>
            <BookChart ticker={ticker} timeframe="weekly" years={2} />
          </div>
          <AnalysisView result={ok} />
          <div className="mt-8">
            <h2 className="mb-3 text-lg font-semibold tracking-tight">종목 정보</h2>
            <StockContextTabs ticker={ticker} />
          </div>
        </>
      )}
    </div>
  );
}
