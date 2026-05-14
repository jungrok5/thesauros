import { api } from "@/lib/api";
import { TickerSearch } from "@/components/ticker-search";
import { AnalysisView } from "@/components/analysis-view";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function StockDetailPage({ params }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw).toUpperCase();

  let result;
  let error: string | null = null;
  try {
    result = await api.analyze(ticker, 5);
  } catch (e) {
    error = String(e);
  }

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

      {error || !result ? (
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
        <AnalysisView result={result} />
      )}
    </div>
  );
}
