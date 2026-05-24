/**
 * TickerSignalHistory — shows how this ticker has reacted to book
 * signals historically (17yr sweep_all_17yr.csv).
 *
 * Server component. The 1.5MB master JSON loads ONCE per server
 * instance into a module-level cache, then per-page renders just
 * filter their ticker's slice. ~0ms after warm-up.
 *
 * Signal label mapping uses signal-labels.ts (Korean book terms).
 */
import fs from "node:fs/promises";
import path from "node:path";
import { labelFor } from "@/lib/signal-labels";

interface TickerSignalStats {
  [signal_type: string]: {
    n: number;
    avg_pct: number;
    win_pct: number;
    median_pct: number;
  };
}

type AllStats = Record<string, TickerSignalStats>;

let STATS_CACHE: AllStats | null = null;
let STATS_LOAD_PROMISE: Promise<AllStats> | null = null;

async function loadAllStats(): Promise<AllStats> {
  if (STATS_CACHE) return STATS_CACHE;
  if (STATS_LOAD_PROMISE) return STATS_LOAD_PROMISE;
  STATS_LOAD_PROMISE = (async () => {
    const p = path.join(process.cwd(), "public", "ticker-signal-stats.json");
    try {
      const text = await fs.readFile(p, "utf-8");
      const parsed = JSON.parse(text) as AllStats;
      STATS_CACHE = parsed;
      return parsed;
    } catch {
      STATS_CACHE = {};
      return {};
    } finally {
      STATS_LOAD_PROMISE = null;
    }
  })();
  return STATS_LOAD_PROMISE;
}

async function loadTickerStats(ticker: string): Promise<TickerSignalStats | null> {
  const all = await loadAllStats();
  return all[ticker] ?? null;
}

// Per-signal SL=10% impact (from sweep_per_signal_sl 2026-05-24).
// Used to chip-tag whether SL helps or hurts THIS signal.
const SL_POLICY: Record<string, "helps" | "neutral" | "hurts"> = {
  volume_case_3: "helps",
  action_strong_buy: "helps",
  pattern_double_bottom: "neutral",
  pattern_catalyst_candle: "neutral",
  pattern_ma240_breakout: "neutral",
  pattern_forking: "neutral",
  pattern_triple_bottom: "hurts",
  volume_case_7: "hurts",
  volume_case_12: "hurts",
  action_buy: "hurts",
};

export async function TickerSignalHistory({ ticker }: { ticker: string }) {
  const stats = await loadTickerStats(ticker);

  if (!stats || Object.keys(stats).length === 0) {
    return (
      <div className="rounded-md border border-border bg-card/50 p-3 text-sm text-muted-foreground">
        이 종목은 17년 백테스트에서 책 신호 3회 이상 발생한 적이 없습니다.
      </div>
    );
  }

  const rows = Object.entries(stats)
    .map(([sig, s]) => ({ sig, ...s }))
    .sort((a, b) => b.avg_pct * b.n - a.avg_pct * a.n);

  return (
    <section className="rounded-lg border border-border bg-card p-4 space-y-3">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold tracking-tight">
          📊 이 종목의 책 신호 history (17년)
        </h3>
        <span className="text-xs text-muted-foreground">
          8주 hold 기준 — 신호 fire 후 다음 8주 평균 결과
        </span>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs uppercase text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left py-1.5 pr-2">신호</th>
              <th className="text-right py-1.5 px-2">발생</th>
              <th className="text-right py-1.5 px-2">평균</th>
              <th className="text-right py-1.5 px-2">중앙값</th>
              <th className="text-right py-1.5 px-2">승률</th>
              <th className="text-right py-1.5 pl-2">SL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const policy = SL_POLICY[r.sig] ?? "neutral";
              const chipClass =
                policy === "helps"
                  ? "text-emerald-700 dark:text-emerald-300 bg-emerald-500/10"
                  : policy === "hurts"
                  ? "text-rose-700 dark:text-rose-300 bg-rose-500/10"
                  : "text-zinc-700 dark:text-zinc-300 bg-zinc-500/10";
              const chipText = policy === "helps" ? "ON 권장" :
                               policy === "hurts" ? "OFF 권장" : "중립";
              return (
                <tr key={r.sig} className="border-b border-border/50 last:border-0">
                  <td className="py-2 pr-2">
                    {labelFor(r.sig).label}
                    <span className="ml-1 font-mono text-xs text-muted-foreground">
                      ({r.sig})
                    </span>
                  </td>
                  <td className="text-right px-2">{r.n}</td>
                  <td className={`text-right px-2 ${r.avg_pct > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                    {r.avg_pct >= 0 ? "+" : ""}{r.avg_pct.toFixed(1)}%
                  </td>
                  <td className={`text-right px-2 ${r.median_pct > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                    {r.median_pct >= 0 ? "+" : ""}{r.median_pct.toFixed(1)}%
                  </td>
                  <td className="text-right px-2 text-muted-foreground">
                    {r.win_pct.toFixed(0)}%
                  </td>
                  <td className="text-right pl-2">
                    <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${chipClass}`}>
                      {chipText}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-muted-foreground leading-relaxed">
        이 표는 <strong>이 종목 한정</strong> 17년 historical 결과 (소문자 sig
        는 raw 키). 책 전략 production 의 top-5 신호 (volume_case_3,
        action_strong_buy, volume_case_7, pattern_ma240_breakout, pattern_forking)
        중 SL ON 권장 = volume_case_3 + action_strong_buy.
      </div>
    </section>
  );
}
