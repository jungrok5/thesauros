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
import { headers } from "next/headers";
import { decideBackLink } from "@/lib/back-link";
import { isAnalysisStale } from "@/lib/market-staleness";
import { AnalysisView } from "@/components/analysis-view";
import { WatchlistButton } from "@/components/watchlist-button";
import { StockContextTabs } from "@/components/stock-context-tabs";
import { FundamentalVerdicts } from "@/components/fundamental-verdicts";
import {
  MarketWarningBanner,
  ShortAndDividendCards,
} from "@/components/market-signals";
import {
  ConsensusCard,
  HoldersCard,
  EarningsCalendarCard,
} from "@/components/investor-intel-cards";
import { VolumeSurgeCard } from "@/components/volume-surge-card";
import { fetchStockContext } from "@/lib/stock-context";
import { CompanyProfile } from "@/components/company-profile";
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

interface CachedAnalysis {
  result: AnalysisResult | null;
  /** True when the row's `as_of` is older than the expected latest
   *  completed trading day for the ticker's market — or when there's
   *  no row at all. The UI surfaces "분석 갱신 중" and the page
   *  dispatches an analyze-ticker workflow in parallel.
   *
   *  Market-aware staleness (see lib/market-staleness.ts) replaced
   *  the older 24h TTL: a KR ticker viewed at 19:00 KST should already
   *  have today's close, not Mon's. */
  stale: boolean;
}

async function getAnalysis(ticker: string): Promise<CachedAnalysis> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("analyze_results")
    .select("result, updated_at")
    .eq("ticker", ticker)
    .maybeSingle();
  if (error) {
    console.error("analyze_results read:", error.message);
    return { result: null, stale: true };
  }
  if (!data) return { result: null, stale: true };
  const result = (data.result as AnalysisResult | undefined) ?? null;
  const stale = !result || isAnalysisStale(ticker, data.updated_at as string);
  return { result, stale };
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

export default async function StockDetailPage({ params }: PageProps) {
  const { ticker: rawSegment } = await params;
  const raw = decodeURIComponent(rawSegment);

  const headersList = await headers();
  const back = decideBackLink(headersList.get("referer"));

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

  const [cached, watch, flow, ctx] = await Promise.all([
    isCanonical ? getAnalysis(ticker) : Promise.resolve<CachedAnalysis>({ result: null, stale: true }),
    isCanonical ? getWatchlistState(ticker) : Promise.resolve({ added: false, category: "observing" as const }),
    isCanonical ? getFlowSummary(ticker) : Promise.resolve(null),
    isCanonical
      ? fetchStockContext(ticker)
      : Promise.resolve({
          disclosures: [],
          fin: null,
          fac: null,
          warnings: [],
          shorts: [],
          dividend: null,
          consensus: [],
          holders: [],
          earnings: [],
          latestBar: null,
          volumeSurge: null,
        }),
  ]);
  const result = cached.result;

  // On-demand analysis trigger — fire-and-forget. Search-only pivot:
  // out-of-watchlist tickers no longer hit the nightly scan, so when
  // a user opens /stocks/[ticker] and the cached row is missing or
  // stale (> 24 h), we dispatch the analyze-ticker.yml workflow so
  // the next page load shows fresh data (~2-3 min later). No-op when
  // GITHUB_DISPATCH_TOKEN is absent (e.g. local dev).
  if (isCanonical && cached.stale) {
    const { dispatchAnalyzeTicker } = await import("@/lib/github-dispatch");
    // Don't await — the page render must not block on the dispatch.
    dispatchAnalyzeTicker(ticker).catch(() => {});
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <Link
        href={back.href}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {back.label}
      </Link>

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

      {/* Company overview renders for every canonical ticker, even when
          analysis hasn't been computed yet — it's purely external data
          (DART / SEC) and matches the "what is this company?" question
          a user has the moment they open the page. */}
      {isCanonical && <CompanyProfile ticker={ticker} />}

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
          {cached.stale && (
            <div className="rounded-md border border-sky-500/40 bg-sky-500/5 px-3 py-2 text-xs text-sky-700 dark:text-sky-300">
              🔄 캐시된 분석을 보여드립니다 — 백그라운드에서 최신 분석이
              진행 중입니다 (~3분). 잠시 후 새로고침하면 최신 결과가 표시됩니다.
            </div>
          )}
          {/* CRITICAL: warning banner before anything else. If a stock
              is 거래정지 / 관리종목, every other widget below is
              irrelevant to the buy/sell decision. */}
          <MarketWarningBanner warnings={ctx.warnings} />
          <MarketHoursNotice />
          <LastClose ticker={ticker} />
          <InvestorFlow ticker={ticker} />
          {/* 240MA 분석 미가능 안내 — bars 가 240주 미만이면 240MA
              계산 불가. 대부분 신규 상장 종목 (예: 두산로보틱스 2023) 이
              본질적 원인. backfill 시도 실패 확인 (2026-05-20) — FDR/Naver
              가 상장 이전 데이터 자체를 모름. */}
          {result?.trend?.weekly?.ma_240 == null && (
            <div className="rounded-md border border-zinc-500/40 bg-zinc-500/5 px-3 py-2 text-xs leading-relaxed">
              <div className="text-zinc-700 dark:text-zinc-300 font-medium">
                ⏳ 240MA 분석 미가능 — 240주 (약 4.6년) 의 데이터가 아직 부족
              </div>
              <div className="mt-1 text-muted-foreground">
                대부분 <strong>신규 상장 종목</strong> 이라 본질적 한계 (상장
                이전 데이터 없음). 대안: <strong>월봉 + 주봉 10MA</strong> 위주로
                추세 판단. 시간이 흐르면 자동으로 240MA 가능해집니다.
              </div>
            </div>
          )}
          {/* 분석 가격 (analyze_results.last_close) 가 bars 최신 종가와
              다를 때 명시 — analyze_results 는 watchlist 외 종목엔 며칠~
              주 단위 stale. entry_plan / 4등분선 등 분석 결과는 분석 시점
              가격 기준이라 사용자가 두 가격 차이 인지해야 정확한 판단. */}
          {result && ctx.latestBar &&
           Math.abs(result.last_close - ctx.latestBar.close) / ctx.latestBar.close > 0.005 && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed">
              <div className="text-amber-700 dark:text-amber-300 font-medium">
                📊 분석 기준 가격 ({result.last_close.toLocaleString("ko-KR")}원)
                과 최신 주봉 종가 ({ctx.latestBar.close.toLocaleString("ko-KR")}원,
                {ctx.latestBar.bar_date})가 다릅니다 ·
                {((ctx.latestBar.close / result.last_close - 1) * 100).toFixed(1)}%
              </div>
              <div className="mt-1 text-muted-foreground">
                매수 자리 (진입/손절/목표) 는 <strong>분석 시점 가격 기준</strong>입니다.
                최신 가격이 진입가 ±5% 안이면 그대로 유효, 너무 멀어졌으면 추격 매수 X.
                관심 종목 추가 시 자동 재분석됩니다.
              </div>
            </div>
          )}
          <AnalysisView result={result} flow={flow} />
          <FundamentalVerdicts fin={ctx.fin} fac={ctx.fac} />
          <ShortAndDividendCards
            shorts={ctx.shorts}
            dividend={ctx.dividend}
            todayIso={new Date().toISOString().slice(0, 10)}
          />
          {/* 거래량 폭증 정보 — /volume-surge 페이지의 같은 메트릭을
              단일 종목으로 표시. 폭증 목록에서 종목 상세 들어왔을 때
              연속된 맥락 제공. */}
          <VolumeSurgeCard surge={ctx.volumeSurge} />
          {/* 투자자 인텔 카드들 — 데이터 없으면 각 카드가 자체적으로
              null 반환해서 렌더 안 됨. 따로 if 분기 안 해도 됨. */}
          <ConsensusCard
            consensus={ctx.consensus}
            lastClose={result?.last_close ?? null}
          />
          <HoldersCard holders={ctx.holders} />
          <EarningsCalendarCard earnings={ctx.earnings} />
          <div>
            <h2 className="mb-2 text-lg font-semibold tracking-tight">
              차트 (시각적 검증)
            </h2>
            <p className="mb-2 text-xs text-muted-foreground leading-relaxed">
              매매 결론은 위 정리표 + 한 줄 평이 끝냅니다. 이 차트는 결론의
              근거를 시각적으로 검증하는 용도. 크게 보기 버튼으로 확대.
            </p>
            <ul className="mb-3 text-xs text-muted-foreground space-y-0.5 leading-relaxed">
              <li>
                <span className="text-rose-600 dark:text-rose-400">빨간선 (240MA)</span> —
                약 5년 평균선. 이 위면 장기 상승 추세, 아래면 약세.
              </li>
              <li>
                <span className="text-emerald-600 dark:text-emerald-400">녹색선 (주봉 10MA)</span> —
                10주 평균선. 단기 추세 — 가격이 위면 매수 우위, 아래면 매도 우위.
              </li>
              <li>
                <span className="text-foreground">가로 수평선 (4등분선)</span> —
                직전 장대양봉을 4 등분한 매매 자리. 0% (몸통 바닥) / 25% / 50% / 75% / 100% (몸통 천장)
                다섯 라인. 25% 깨지면 책 정신상 손절 시그널.
              </li>
            </ul>
            <BookChart ticker={ticker} timeframe="weekly" years={5} />
          </div>
          <div className="mt-8">
            <h2 className="mb-3 text-lg font-semibold tracking-tight">
              종목 정보
            </h2>
            <StockContextTabs
              ticker={ticker}
              disclosures={ctx.disclosures}
              fin={ctx.fin}
              fac={ctx.fac}
            />
          </div>
        </>
      )}
    </div>
  );
}
