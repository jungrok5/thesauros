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
import { NextDecisionChip } from "@/components/next-decision-chip";
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
  /** Originating-page hint set by list pages on their stock <Link>.
   *  Keys we honor: `from`, `preset` (for /screener), `theme` (for
   *  /themes/[id]). Falls back to Referer header if absent. */
  searchParams: Promise<Record<string, string | undefined>>;
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

async function getAnalysis(
  ticker: string,
): Promise<{ result: AnalysisResult | null; updatedAt: string | null }> {
  // 주봉/월봉 pivot 후 scan_daily 는 금요일 17 KST 에만 의미 있게
  // 갱신됨 (W bar 가 Mon-Thu 에 안 바뀜). 따라서 daily 기준 stale
  // 판정 + on-demand dispatch 는 평일에 처음 열어보는 종목마다 매번
  // 트리거되어 노이즈만 발생 — 2026-05-20 제거. 결과가 있으면 그대로
  // 보여주고, 없으면 "분석 대기" 안내만 한다.
  //
  // updated_at 도 같이 fetch — BookVerdict header chip 의 "🗓️ N월 N일
  // 분석" 표시용. result.as_of / last_candle.date 둘 다 analyzer 가
  // "다음 결산일" (미래 금요일) 로 stamp 해서 사용자에게 미래 시점으로
  // 읽힌다 (088350.KS 2026-05-20 reported case: "2026-05-22 분석"
  // 으로 표시됨). updated_at = 실제 분석 실행 timestamp 라 자연스러움.
  const sb = getServerClient();
  const { data, error } = await sb
    .from("analyze_results")
    .select("result, updated_at")
    .eq("ticker", ticker)
    .maybeSingle();
  if (error) {
    console.error("analyze_results read:", error.message);
    return { result: null, updatedAt: null };
  }
  return {
    result: (data?.result as AnalysisResult | undefined) ?? null,
    updatedAt: (data?.updated_at as string | undefined) ?? null,
  };
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

export default async function StockDetailPage({ params, searchParams }: PageProps) {
  const { ticker: rawSegment } = await params;
  const raw = decodeURIComponent(rawSegment);

  const headersList = await headers();
  const sp = await searchParams;
  const back = decideBackLink(headersList.get("referer"), sp);

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

  const [analysis, watch, flow, ctx] = await Promise.all([
    isCanonical
      ? getAnalysis(ticker)
      : Promise.resolve<{ result: AnalysisResult | null; updatedAt: string | null }>({ result: null, updatedAt: null }),
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
  const result = analysis.result;
  const analyzedAt = analysis.updatedAt;

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
            action={result?.action ?? null}
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
          {/* ─────────────────────────────────────────────────────────
              그룹 1. 매매 결정 — 책 정신 핵심.
              위험 경고 → 시장 상태 → 실시간 종가 → 한 줄 평 + 정리표.
              사용자가 페이지 열고 "사야 하나/팔아야 하나" 즉답이 끝나는
              최상단 fold. 페이지 ordering 의 절대적 우선순위.
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-3">
            {/* CRITICAL: 거래정지 / 관리종목 이면 아래 위젯 다 무의미. */}
            <MarketWarningBanner warnings={ctx.warnings} />
            {/* 240MA 미계산 = 신규 상장 → 책 정신상 안전 게이트 결여. */}
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
            <MarketHoursNotice />
            <LastClose ticker={ticker} />
            {/* 다음 매매 결정 시점 (책 정신: 주봉 종가) — compact chip
                형태로 LastClose 옆에. 사용자가 매일 들여다보는 충동을
                줄이는 게 목적. */}
            <NextDecisionChip compact />
            {/* 분석 시점 vs 현재가 차이는 BookVerdict header chip 통합
                (2026-05-20). chip + trigger-cleared note 가 같은 정보 carry. */}
            <AnalysisView
              result={result}
              flow={flow}
              currentPrice={ctx.latestBar?.close ?? null}
              currentBarDate={ctx.latestBar?.bar_date ?? null}
              analyzedAt={analyzedAt}
            />
          </section>

          {/* ─────────────────────────────────────────────────────────
              그룹 2. 차트 — 결정의 시각 검증
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-2">
            <h2 className="text-lg font-semibold tracking-tight">
              📈 차트 (시각 검증)
            </h2>
            <p className="text-xs text-muted-foreground leading-relaxed">
              매매 결론은 위 한 줄 평 + 정리표가 끝냅니다. 이 차트는 결론의
              근거를 시각적으로 확인하는 용도.
            </p>
            <ul className="text-xs text-muted-foreground space-y-0.5 leading-relaxed">
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
                직전 장대양봉을 4 등분한 매매 자리. 0% / 25% / 50% / 75% / 100%.
                25% 깨지면 책 정신상 손절.
              </li>
            </ul>
            <BookChart ticker={ticker} timeframe="weekly" years={5} />
          </section>

          {/* ─────────────────────────────────────────────────────────
              그룹 3. 시장 흐름 — 큰 손 + 거래량.
              실시간 종가는 그룹 1 에 있고, 여기는 "수급 + 거래량" 두 축.
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">
              💸 시장 흐름 (수급 · 거래량)
            </h2>
            <InvestorFlow ticker={ticker} />
            <VolumeSurgeCard surge={ctx.volumeSurge} asOf={ctx.latestBar?.bar_date ?? null} />
          </section>

          {/* ─────────────────────────────────────────────────────────
              그룹 4. 펀더멘털 검증 — PER/PBR/ROE + 배당/공매도.
              차트는 추세, 여기는 회사의 "재무 상태".
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">
              🏛️ 펀더멘털 검증
            </h2>
            <FundamentalVerdicts fin={ctx.fin} fac={ctx.fac} />
            <ShortAndDividendCards
              shorts={ctx.shorts}
              dividend={ctx.dividend}
              todayIso={new Date().toISOString().slice(0, 10)}
            />
          </section>

          {/* ─────────────────────────────────────────────────────────
              그룹 5. 외부 의견 / 일정 — 참고 정보.
              컨센서스 (목표주가) + 큰손 5% 지분 + 실적 발표 일정. 각
              카드는 데이터 없으면 자체적으로 null 반환해서 렌더 X.
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">
              🔍 외부 의견 · 일정
            </h2>
            <ConsensusCard
              consensus={ctx.consensus}
              currentPrice={ctx.latestBar?.close ?? result?.last_close ?? null}
              asOf={ctx.consensus[0]?.updated_at ?? null}
            />
            <HoldersCard holders={ctx.holders} />
            <EarningsCalendarCard earnings={ctx.earnings} />
          </section>

          {/* ─────────────────────────────────────────────────────────
              그룹 6. 심화 정보 — 공시 / 재무 / 펀더 상세 탭.
              ───────────────────────────────────────────────────────── */}
          <section className="space-y-2">
            <h2 className="text-lg font-semibold tracking-tight">
              📋 종목 정보 (상세)
            </h2>
            <StockContextTabs
              ticker={ticker}
              disclosures={ctx.disclosures}
              fin={ctx.fin}
              fac={ctx.fac}
            />
          </section>
        </>
      )}
    </div>
  );
}
