/**
 * /us-analysis — Phase 6 ad-hoc US ticker analysis.
 *
 * Replaces the old /chart-vision (vision-based image analysis, low
 * accuracy). User searches a US ticker → backend fetches 5y weekly +
 * monthly bars from Tiingo → runs full book analyzer → returns
 * AnalysisResult identical shape to KR /stocks/[ticker].
 *
 * Login-gated (sidebar nav only shows for logged-in users).
 *
 * Cache strategy: per-ticker 7d in us_bars + us_ticker_cache. First
 * fetch ≈ 3-5s (Tiingo round-trip + analyze). Subsequent loads ≈ 0.5s.
 */
import { UsAnalysisSearch } from "@/components/us-analysis-search";

export const dynamic = "force-dynamic";

export default function UsAnalysisPage() {
  return (
    <div className="space-y-6 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          🇺🇸 미국 주식 책 분석
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          미국 종목을 ticker 로 검색하면 Tiingo 에서 5년 weekly+monthly bars 를
          fetch 한 후 책 정신 분석 (17 패턴 + 240MA + 거래량 케이스) 을 수행합니다.
          캐시 7일 — 동일 종목 재검색 시 즉시 응답.
        </p>
      </header>

      <UsAnalysisSearch />

      <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm space-y-2">
        <h2 className="font-medium text-amber-700 dark:text-amber-300">
          ⚠️ 책 정신 안내
        </h2>
        <ul className="text-muted-foreground space-y-1 list-disc pl-5">
          <li>
            관심종목/보유종목 등록 불가 — KR 시장 매매 중심 (책 정신상).
          </li>
          <li>
            ad-hoc 분석 전용. cron/daily-scan 대상 아님.
          </li>
          <li>
            데이터: Tiingo 무료 tier (500 req/day). 동시 많은 검색 시 한도 도달
            가능.
          </li>
          <li>
            분석 정확도는 KR 과 동일 (같은 book pipeline). 단 미국 종목 종가 시점
            (NY 16:00 = KST 06:00) 과 책 정신 (주봉 종가) 의 timezone 차이 주의.
          </li>
        </ul>
      </section>
    </div>
  );
}
