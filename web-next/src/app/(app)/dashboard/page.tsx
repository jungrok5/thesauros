import { api, type MacroSnapshot } from "@/lib/api";
import { RegimeBadge } from "@/components/regime-badge";
import { StatePill } from "@/components/state-pill";
import { MacroDial } from "@/components/macro-dial";
import { formatNumber, formatPct } from "@/lib/utils";

export const dynamic = "force-dynamic";

async function fetchSnapshot(): Promise<{
  data: MacroSnapshot | null;
  error: string | null;
}> {
  try {
    const data = await api.macroSnapshot();
    return { data, error: null };
  } catch (e) {
    return { data: null, error: String(e) };
  }
}

export default async function DashboardPage() {
  const { data, error } = await fetchSnapshot();

  if (error || !data) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">Macro</h1>
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm">
          <div className="font-medium text-rose-700 dark:text-rose-300">
            FastAPI 백엔드에 연결할 수 없습니다.
          </div>
          <div className="mt-2 text-rose-600/80 dark:text-rose-200/80 font-mono text-xs">
            {error}
          </div>
          <div className="mt-3 text-muted-foreground">
            백엔드 실행:{" "}
            <code className="bg-muted px-1 rounded">
              python -m uvicorn app.api.server:app --reload --port 8001
            </code>
          </div>
        </div>
      </div>
    );
  }

  const { regime, indicators } = data;
  const ts = new Date().toLocaleString("ko-KR");

  return (
    <div className="space-y-8 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Macro</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            책 1부 거시 지표 25개 · 자동 상태 분류 · 시장 레짐 ·{" "}
            <span className="font-mono opacity-70">{ts}</span>
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
        <div className="text-xs text-muted-foreground mt-2 flex items-center gap-4">
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
                <div className="flex items-baseline gap-2 mb-2">
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
