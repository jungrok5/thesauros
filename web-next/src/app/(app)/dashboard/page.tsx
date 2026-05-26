/**
 * Dashboard — macro overview. Reads everything from Supabase `macro_state`
 * (populated daily by the `publish_macro` cron). Pure Supabase, no FastAPI.
 *
 * UX restructure (2026-05-19): "오늘의 액션" 한 줄 결론 + 다음 단계
 * 버튼을 최상단으로 끌어올림. 시장 레짐 + 5축 다이얼 + VIX / 수익률곡선 /
 * MV=PQ를 한 카드(MarketActionCard)에 통합 (이전엔 3군데 중복). 거시
 * 지표 34개 카드는 핵심 8개만 우선 노출, 나머지는 펼침 토글.
 */
import Link from "next/link";
import { Compass } from "lucide-react";
import { BookEntrySpots } from "@/components/book-entry-spots";
import { StatePill } from "@/components/state-pill";
import { HelpTip } from "@/components/help-tip";
import { GlobalNews } from "@/components/global-news";
import { MarketTicker } from "@/components/market-ticker";
import { MarketActionCard } from "@/components/market-action-card";
import { SeasonalBanner } from "@/components/seasonal-banner";
import { indicatorVerdict } from "@/lib/macro-interpret";
import { GLOSSARY } from "@/lib/glossary";
import { formatNumber, formatPct } from "@/lib/utils";
import { getServerClient } from "@/lib/supabase";
import { DataFreshness } from "@/components/data-freshness";

// macro_state.macro_indicators 에는 'KOSPI 지수' / '환율' / 'VIX' 같은
// 실시간성 지표도 섞여 들어옵니다 (publish_macro 가 yfinance/FRED 일괄
// fetch). 하루-stale 가격이 의미 없으니 dashboard 카드에서는 빼고,
// 실시간 띠 (MarketTicker) 에서만 노출합니다.
const FAST_INDICATOR_KEYS = new Set<string>([
  "kospi", "kosdaq", "sp500", "nasdaq", "dow", "djia",
  "vix", "usdkrw", "usdjpy", "usdcny", "krwusd",
  "us10y", "us2y", "tnx",
  "wti", "brent", "gold", "btc", "bitcoin",
]);

// Map indicator key (from `macro_state.macro_indicators`) → glossary slug.
// Anything not in this map falls back to plain text (no tooltip).
const INDICATOR_TIPS: Record<string, string> = {
  tips_10y: "tips_spread",
  tips_spread: "tips_spread",
  ppi_yoy: "ppi_yoy",
  cpi_yoy: "cpi_yoy",
  vix: "vix_state",
  yield_curve: "yield_curve",
  mv_pq: "mv_pq",
};

// Indicators that materially shape the buy/sell decision (book p324 +
// chapter 7 탑다운). Surfaced as "핵심 거시" above the fold; rest fold
// under a <details> toggle so the page doesn't dump 34 cards at once.
// Keys must match macro_state.macro_indicators (populated by
// app.macro.state via publish_macro cron — see actual snapshot).
const CORE_INDICATORS = new Set<string>([
  "cpi",                  // 소비자물가지수 (CPI YoY)
  "ppi",                  // 생산자물가지수 (PPI YoY)
  "m2_supply",            // M2 통화공급량
  "real_rate_10y",        // 10년 실질금리
  "fed_funds_rate",       // 미 연방기금금리
  "yield_curve_10y_2y",   // 수익률곡선 10Y-2Y
  "yield_curve_10y_3m",   // 수익률곡선 10Y-3M
  "credit_spread_hy",     // HY 정크채 스프레드 (책: 리스크온/오프 시그널)
  "dxy",                  // DXY 달러 지수
  "tips_breakeven_10y",   // 기대 인플레이션
]);

// Macro state changes once per day via cron; 60s ISR is a generous
// upper bound that lets the page serve from cache to subsequent users.
export const revalidate = 60;

type IndicatorState = {
  key: string;
  name_kr: string;
  category: string;
  book_ref: string;
  desc: string;
  value: number | null;
  as_of: string | null;
  yoy_pct: number | null;
  state: "BULL" | "NEUTRAL" | "CAUTION" | "BEAR";
  verdict: string;
  unit: string;
};

type Regime = {
  regime: string;
  score: number;
  n_indicators: number;
  vix_state: string | null;
  yield_curve_inverted: boolean;
  note: string;
};

type MacroStateRow = {
  global_status: string | null;
  kr_status: string | null;
  indices: Record<string, string> | null;
  macro_indicators: Record<string, IndicatorState> | null;
  mv_pq_signal: string | null;
  dial_scores: Record<string, number> | null;
  one_line_guidance: string | null;
  regime: Regime | null;
  updated_at: string;
};

async function fetchMacro(): Promise<MacroStateRow | null> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("macro_state")
    .select(
      "global_status, kr_status, indices, macro_indicators, mv_pq_signal, " +
        "dial_scores, one_line_guidance, regime, updated_at",
    )
    .eq("id", 1)
    .maybeSingle();
  if (error) {
    console.error("macro_state read:", error.message);
    return null;
  }
  return data as MacroStateRow | null;
}

function categorize(
  indicators: Record<string, IndicatorState>,
): Record<string, IndicatorState[]> {
  const out: Record<string, IndicatorState[]> = {};
  for (const [key, ind] of Object.entries(indicators)) {
    // Skip fast-moving indicators — they're rendered in <MarketTicker/>
    // up top with 1-minute freshness. Leaving day-stale duplicates
    // here would just confuse readers.
    if (FAST_INDICATOR_KEYS.has(key.toLowerCase())) continue;
    const cat = ind.category || "기타";
    (out[cat] ??= []).push(ind);
  }
  for (const cat of Object.keys(out)) {
    out[cat].sort((a, b) => a.name_kr.localeCompare(b.name_kr, "ko-KR"));
  }
  return out;
}

export default async function DashboardPage() {
  const row = await fetchMacro();

  if (!row || !row.macro_indicators || !row.regime) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Compass className="h-6 w-6" /> 거시 (Macro)
        </h1>
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
          <div className="font-medium text-amber-700 dark:text-amber-300">
            거시 데이터가 아직 발행되지 않았습니다.
          </div>
          <div className="mt-2 text-muted-foreground">
            매일 자동으로 갱신됩니다. 수동 발행:{" "}
            <code className="bg-muted px-1 rounded">
              python -m app.db.publish_macro
            </code>
          </div>
        </div>
      </div>
    );
  }

  const regime = row.regime;
  const allIndicators = Object.values(row.macro_indicators).filter(
    (it) => !FAST_INDICATOR_KEYS.has(it.key.toLowerCase()),
  );
  const core = allIndicators
    .filter((it) => CORE_INDICATORS.has(it.key.toLowerCase()))
    .sort((a, b) => a.name_kr.localeCompare(b.name_kr, "ko-KR"));
  const restByCategory = categorize(
    Object.fromEntries(
      allIndicators
        .filter((it) => !CORE_INDICATORS.has(it.key.toLowerCase()))
        .map((it) => [it.key, it]),
    ) as Record<string, IndicatorState>,
  );
  const updatedAt = new Date(row.updated_at).toLocaleString("ko-KR");
  const restCount = allIndicators.length - core.length;

  return (
    <div className="space-y-6 max-w-7xl">
      <header>
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Compass className="h-6 w-6" /> 거시 (Macro)
          </h1>
          <DataFreshness asOf={row.updated_at} cadence="daily" />
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          탑다운 1 단계 — 시장 전체 분위기 진단. 매크로가 약세면 개별 종목
          아무리 좋아도 진입 자제. 실시간 시세는 위쪽 띠, 월/분기 지표는 카드로.
        </p>
      </header>

      <MarketTicker />

      <SeasonalBanner
        todayIso={new Date().toISOString().slice(0, 10)}
      />

      <MarketActionCard
        guidance={row.one_line_guidance}
        regime={regime.regime}
        regimeScore={regime.score}
        regimeNote={regime.note}
        dialScores={row.dial_scores}
        vixState={regime.vix_state}
        yieldCurveInverted={regime.yield_curve_inverted}
        mvPqSignal={row.mv_pq_signal}
        updatedAt={updatedAt}
      />

      {/* 책 전략 production winning config (SL=10% / max=8 / 24w / top-5)
          의 이번 주 진입 후보. 거시 카드 직후에 배치해 macro → 실행으로
          내려가는 흐름. */}
      <BookEntrySpots />


      {/* 핵심 거시 지표 — 매매 결정에 직접 닿는 8~10개만 above-the-fold.
          2026-05-26 site review: 초보가 dashboard 들어와서 CPI/PPI/M2/
          Yield curve 등 raw 거시 카드 8개를 봐도 "그래서 사? 말아?" 결론
          못 냄. 결론은 위쪽 MarketActionCard 의 한 줄 평이 함. 거시 카드
          자체는 펼침 토글로 demote — 자세히 알고 싶은 사용자만 펼침. */}
      {core.length > 0 && (
        <details className="rounded-lg border border-border bg-card">
          <summary className="px-4 py-3 cursor-pointer hover:bg-muted/40 flex items-baseline justify-between gap-2">
            <span className="text-sm font-semibold tracking-tight">
              핵심 거시 지표 ({core.length}개)
            </span>
            <span className="text-[11px] text-muted-foreground font-normal">
              자세히 보고 싶을 때만 펼침 — 결론은 위쪽 카드
            </span>
          </summary>
          <div className="px-4 pb-4 pt-2">
            <p className="text-xs text-muted-foreground mb-3">
              책 정신상 매수/회피 자격에 직접 영향을 주는 지표만.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              {core.map((it) => (
                <IndicatorCard key={it.key} it={it} />
              ))}
            </div>
          </div>
        </details>
      )}

      <GlobalNews limit={6} />

      {/* 나머지 지표 — 카테고리별 접힘 */}
      {restCount > 0 && (
        <details className="rounded-lg border border-border bg-card">
          <summary className="px-4 py-3 cursor-pointer text-sm font-semibold tracking-tight hover:bg-muted/40">
            전체 거시 지표 ({restCount}개) — 카테고리별 펼침
          </summary>
          <div className="px-4 pb-4 space-y-5 pt-2">
            {Object.entries(restByCategory).map(([categoryLabel, items]) => (
              <div key={categoryLabel}>
                <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">
                  {categoryLabel}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {items.map((it) => (
                    <IndicatorCard key={it.key} it={it} compact />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Site footer — backtest credibility line. 2026-05-25 demote:
          /backtest page is no longer in the sidebar (was "자랑 페이지"),
          but the 17-year universe-honest result is still the answer to
          "이 시스템 신뢰해도 돼?" so we surface it as a one-liner here
          with the link for users who want to dig in. */}
      <div className="pt-2 mt-2 border-t border-border/60 text-xs text-muted-foreground leading-relaxed">
        이 시스템 17년 백테스트 (KOSPI/KOSDAQ 1820 종목 universe) —{" "}
        <span className="text-foreground">CAGR 13.4% · Sharpe 0.62 · DD 47.6%</span>
        {" "}(KOSPI BH 대비 +1.9%p/y).
        {" "}
        <Link
          href="/backtest"
          className="text-foreground hover:underline whitespace-nowrap"
        >
          백테스트 자세히 →
        </Link>
      </div>
    </div>
  );
}

function IndicatorCard({ it, compact = false }: { it: IndicatorState; compact?: boolean }) {
  const verdict = indicatorVerdict(it.key, it.state, it.value, it.yoy_pct);
  return (
    <article
      className={`rounded-lg border border-border bg-card hover:bg-accent/40 transition-colors ${compact ? "p-3" : "p-4"}`}
    >
      <header className="flex items-start justify-between gap-2 mb-1">
        <div className={`font-medium ${compact ? "text-xs" : "text-sm"} text-foreground`}>
          {INDICATOR_TIPS[it.key] && GLOSSARY[INDICATOR_TIPS[it.key]] ? (
            <HelpTip term={INDICATOR_TIPS[it.key]}>{it.name_kr}</HelpTip>
          ) : (
            it.name_kr
          )}
        </div>
        <StatePill state={it.state} />
      </header>
      <div className="flex items-baseline gap-2 mb-1 flex-wrap">
        <span className={`${compact ? "text-lg" : "text-2xl"} font-mono font-medium`}>
          {formatNumber(it.value)}
        </span>
        <span className="text-xs text-muted-foreground">{it.unit}</span>
        {it.yoy_pct !== null && (
          <span
            className={
              it.yoy_pct >= 0
                ? "text-xs text-emerald-600 dark:text-emerald-400"
                : "text-xs text-rose-600 dark:text-rose-400"
            }
          >
            YoY {formatPct(it.yoy_pct)}
          </span>
        )}
      </div>
      {/* "이 지표가 주식 시장에 어떻게" — 2-line:
          (1) 정적 directional 룰 (값 무관)
          (2) 현재 state 기반 액션 안내 */}
      <p className="text-[11px] text-muted-foreground/90 leading-relaxed">
        💡 {verdict.impact}
      </p>
      <p className="text-xs leading-relaxed mt-1">{verdict.action}</p>
      {/* cron-generated `it.verdict` was previously rendered here as
          a small italic backup. Removed 2026-05-20 (audit): duplicates
          the 💡 impact + action lines above and confuses users with
          "왜 두 줄로 비슷한 말이 두 번 나오지?". Field still exists
          in the DB for legacy compatibility. */}
      {/* as_of 가 없으면 빈 footer 영역을 만들지 않음 — "—" 만 보이던
          무가치 한 줄 제거. */}
      {it.as_of && (
        <div className="mt-2 pt-2 border-t border-border/60 text-[10px] text-muted-foreground/70 text-right">
          {it.as_of}
        </div>
      )}
    </article>
  );
}
