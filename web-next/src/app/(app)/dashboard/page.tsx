/**
 * Dashboard — macro overview. Reads everything from Supabase `macro_state`
 * (populated daily by the `publish_macro` cron). Pure Supabase, no FastAPI.
 */
import { RegimeBadge } from "@/components/regime-badge";
import { StatePill } from "@/components/state-pill";
import { MacroDial } from "@/components/macro-dial";
import { formatNumber, formatPct } from "@/lib/utils";
import { getServerClient } from "@/lib/supabase";

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
  for (const ind of Object.values(indicators)) {
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
          <h1 className="text-2xl font-semibold tracking-tight">Macro</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            책 1부 거시 지표 · 자동 상태 분류 · 시장 레짐 · 업데이트{" "}
            <span className="font-mono opacity-70" suppressHydrationWarning>
              {updatedAt}
            </span>
          </p>
        </div>
        <RegimeBadge regime={regime.regime} score={regime.score} />
      </header>

      <MacroDial />

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
          {regime.vix_state && <span>VIX 상태: {regime.vix_state}</span>}
          <span>
            수익률곡선:{" "}
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
          {row.mv_pq_signal && <span>MV=PQ: {row.mv_pq_signal}</span>}
          {row.one_line_guidance && (
            <span className="basis-full text-foreground/70">
              {row.one_line_guidance}
            </span>
          )}
        </div>
      </section>

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
                    {it.name_kr}
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
                <div className="flex items-center justify-between mt-2 pt-2 border-t border-border/60">
                  <span className="text-[10px] text-muted-foreground/70 font-mono">
                    {it.book_ref}
                  </span>
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
