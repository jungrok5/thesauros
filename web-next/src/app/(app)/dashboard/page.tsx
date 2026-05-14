import { api, type MacroSnapshot } from "@/lib/api";
import { RegimeBadge } from "@/components/regime-badge";
import { StatePill } from "@/components/state-pill";
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
          <div className="font-medium text-rose-300">
            FastAPI 백엔드에 연결할 수 없습니다.
          </div>
          <div className="mt-2 text-rose-200/80 font-mono text-xs">
            {error}
          </div>
          <div className="mt-3 text-zinc-400">
            백엔드 실행:{" "}
            <code className="bg-zinc-900 px-1 rounded">
              python -m uvicorn app.api.server:app --reload
            </code>{" "}
            (port 8000)
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
          <p className="mt-1 text-sm text-zinc-500">
            책 1부 거시 지표 25개 · 자동 상태 분류 · 시장 레짐 ·{" "}
            <span className="font-mono text-zinc-600">{ts}</span>
          </p>
        </div>
        <RegimeBadge regime={regime.regime} score={regime.score} />
      </header>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">
          시장 레짐
        </div>
        <div className="flex items-center gap-3 mb-2">
          <RegimeBadge regime={regime.regime} score={regime.score} />
          <span className="text-sm text-zinc-300">{regime.note}</span>
        </div>
        <div className="text-xs text-zinc-500 mt-2 flex items-center gap-4">
          <span>지표 {regime.n_indicators}개 종합</span>
          {regime.vix_state && <span>VIX 상태: {regime.vix_state}</span>}
          <span>
            수익률곡선:{" "}
            {regime.yield_curve_inverted ? (
              <span className="text-rose-400">역전 (침체 예고)</span>
            ) : (
              <span className="text-emerald-400">정상</span>
            )}
          </span>
        </div>
      </section>

      {Object.entries(indicators).map(([categoryLabel, items]) => (
        <section key={categoryLabel}>
          <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
            {categoryLabel}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((it) => (
              <article
                key={it.key}
                className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4 hover:bg-zinc-900/50 transition"
              >
                <header className="flex items-start justify-between gap-2 mb-1">
                  <div className="font-medium text-sm text-zinc-200">
                    {it.name_kr}
                  </div>
                  <StatePill state={it.state} />
                </header>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-2xl font-mono font-medium text-zinc-100">
                    {formatNumber(it.value)}
                  </span>
                  <span className="text-xs text-zinc-500">{it.unit}</span>
                  {it.yoy_pct !== null && (
                    <span
                      className={
                        it.yoy_pct >= 0
                          ? "text-xs text-emerald-400"
                          : "text-xs text-rose-400"
                      }
                    >
                      YoY {formatPct(it.yoy_pct)}
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-400 mb-2">{it.verdict}</p>
                <div className="flex items-center justify-between mt-2 pt-2 border-t border-zinc-800/60">
                  <span className="text-[10px] text-zinc-600 font-mono">
                    {it.book_ref}
                  </span>
                  <span className="text-[10px] text-zinc-600">
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
