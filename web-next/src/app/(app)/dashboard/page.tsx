/**
 * Dashboard — macro overview. Reads everything from Supabase `macro_state`
 * (populated daily by the `publish_macro` cron). Pure Supabase, no FastAPI.
 */
import { RegimeBadge } from "@/components/regime-badge";
import { StatePill } from "@/components/state-pill";
import { MacroDial } from "@/components/macro-dial";
import { HelpTip } from "@/components/help-tip";
import { GlobalNews } from "@/components/global-news";
import { MarketTicker } from "@/components/market-ticker";
import { GLOSSARY } from "@/lib/glossary";
import { formatNumber, formatPct } from "@/lib/utils";
import { getServerClient } from "@/lib/supabase";

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
        <h1 className="text-2xl font-semibold">Macro</h1>
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
  const indicators = categorize(row.macro_indicators);
  const updatedAt = new Date(row.updated_at).toLocaleString("ko-KR");

  return (
    <div className="space-y-8 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">거시 환경</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            시세 띠는 실시간 (1분 갱신) · 거시 카드는 월간/분기 지표 (매일 자동 집계 · 마지막 갱신{" "}
            <span className="font-mono opacity-70" suppressHydrationWarning>
              {updatedAt}
            </span>
            )
          </p>
        </div>
        <RegimeBadge regime={regime.regime} score={regime.score} />
      </header>

      <MarketTicker />

      <MacroDial />

      <GlobalNews />

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="text-xs uppercase tracking-widest text-muted-foreground mb-2">
          시장 레짐
        </div>
        <div className="flex items-center gap-3 mb-2">
          <RegimeBadge regime={regime.regime} score={regime.score} />
          <span className="text-sm text-foreground/80">{regime.note}</span>
        </div>
        <div className="text-xs text-muted-foreground mt-2 flex items-center gap-4 flex-wrap">
          <span>지표 {regime.n_indicators}개 종합</span>
          {regime.vix_state && (
            <span>
              <HelpTip term="vix_state">VIX 상태</HelpTip>: {regime.vix_state}
            </span>
          )}
          <span>
            <HelpTip term="yield_curve">수익률곡선</HelpTip>:{" "}
            {regime.yield_curve_inverted ? (
              <span className="text-rose-600 dark:text-rose-400">
                역전 (침체 예고)
              </span>
            ) : (
              <span className="text-emerald-600 dark:text-emerald-400">
                정상
              </span>
            )}
          </span>
          {row.mv_pq_signal && (
            <span>
              <HelpTip term="mv_pq">MV=PQ</HelpTip>: {row.mv_pq_signal}
            </span>
          )}
          {row.one_line_guidance && (
            <span className="basis-full text-foreground/70">
              {row.one_line_guidance}
            </span>
          )}
        </div>
      </section>

      <div className="pt-4 border-t border-border/60">
        <h2 className="text-sm font-semibold tracking-tight">월간/분기 거시 지표</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          CPI · PPI · M2 · 실업률 등 발표 빈도가 낮은 지표. 매일 16시 KST cron 으로 갱신.
          실시간 시세는 위 띠를 참고하세요.
        </p>
      </div>

      {Object.entries(indicators).map(([categoryLabel, items]) => (
        <section key={categoryLabel}>
          <h2 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
            {categoryLabel}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((it) => (
              <article
                key={it.key}
                className="rounded-lg border border-border bg-card p-4 hover:bg-accent/40 transition-colors"
              >
                <header className="flex items-start justify-between gap-2 mb-1">
                  <div className="font-medium text-sm text-foreground">
                    {INDICATOR_TIPS[it.key] && GLOSSARY[INDICATOR_TIPS[it.key]] ? (
                      <HelpTip term={INDICATOR_TIPS[it.key]}>{it.name_kr}</HelpTip>
                    ) : (
                      it.name_kr
                    )}
                  </div>
                  <StatePill state={it.state} />
                </header>
                <div className="flex items-baseline gap-2 mb-2 flex-wrap">
                  <span className="text-2xl font-mono font-medium">
                    {formatNumber(it.value)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {it.unit}
                  </span>
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
                <p className="text-xs text-muted-foreground mb-2">
                  {it.verdict}
                </p>
                <div className="flex items-center justify-end mt-2 pt-2 border-t border-border/60">
                  <span className="text-[10px] text-muted-foreground/70">
                    {it.as_of ?? "—"}
                  </span>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
