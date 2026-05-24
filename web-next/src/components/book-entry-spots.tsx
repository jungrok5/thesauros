/**
 * BookEntrySpots — "이번 주 책 진입 자리" card.
 *
 * Queries scan_results for top-5 entry signals (production: no-SL /
 * max=50 / 24w / top-5) fired in the last 7 days, ordered by strength
 * desc. Shows top-N candidates the user could enter THIS WEEK if they
 * were running the production strategy live.
 *
 * Universe-honest production winner (Sprint 2.1, 2026-05-24):
 *   - no-SL / max=50 — full 1820-ticker universe
 *   - +795% / CAGR 13.4% / Sharpe 0.62 / DD 47.6%
 *   - alpha +1.91%/y over KOSPI BH (modest but real)
 *
 * 100-tic seed=42 sample result (max=8 / SL=10%) was over-fit and
 * underperformed -8.8%/y on universe. Trust universe numbers.
 *
 * Top-5 signals:
 *   volume_case_3, pattern_forking, volume_case_7,
 *   action_strong_buy, pattern_ma240_breakout
 *
 * Per-signal SL policy still useful (volume_case_3 + action_strong_buy
 * benefit from SL even on universe — TODO: verify and split).
 */
import Link from "next/link";
import { getServerClient } from "@/lib/supabase";
import { labelFor } from "@/lib/signal-labels";

const TOP_5_ENTRY = [
  "volume_case_3",
  "pattern_forking",
  "volume_case_7",
  "action_strong_buy",
  "pattern_ma240_breakout",
] as const;

const SL_ON_PREFERRED = new Set<string>([
  "volume_case_3",
  "action_strong_buy",
]);

// Universe-honest production allows max=50 positions, but dashboard
// card shows top-12 for readability. Full list available in /screener.
const DEFAULT_LIMIT = 12;

type Spot = {
  ticker: string;
  ticker_name: string | null;
  signal_type: string;
  strength: number;
  detected_at: string;
  reason: string | null;
};

async function fetchSpots(limit: number): Promise<Spot[]> {
  const sb = getServerClient();
  const since = new Date(Date.now() - 7 * 86_400_000).toISOString();
  const { data, error } = await sb
    .from("scan_results")
    .select("ticker, signal_type, strength, detected_at, reason, tickers(name)")
    .in("signal_type", TOP_5_ENTRY as unknown as string[])
    .eq("is_active", true)
    .gte("detected_at", since)
    .order("strength", { ascending: false })
    .limit(limit * 3);     // over-fetch to dedup by ticker
  if (error) {
    console.error("BookEntrySpots fetch:", error.message);
    return [];
  }
  // Dedup by ticker — multiple signals same ticker = take strongest
  const seen = new Set<string>();
  const out: Spot[] = [];
  for (const r of data ?? []) {
    if (seen.has(r.ticker)) continue;
    seen.add(r.ticker);
    const tickersField = (r as unknown as {
      tickers?: { name: string } | { name: string }[] | null;
    }).tickers;
    const ticker_name = Array.isArray(tickersField)
      ? (tickersField[0]?.name ?? null)
      : (tickersField?.name ?? null);
    out.push({
      ticker: r.ticker,
      ticker_name,
      signal_type: r.signal_type,
      strength: Number(r.strength) || 0,
      detected_at: r.detected_at,
      reason: r.reason,
    });
    if (out.length >= limit) break;
  }
  return out;
}

export async function BookEntrySpots({ limit = DEFAULT_LIMIT }: { limit?: number } = {}) {
  const spots = await fetchSpots(limit);

  if (spots.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="text-sm text-muted-foreground">
          이번 주 책 전략 (top-5 신호) fire 종목이 없습니다. 다음 주봉 마감 시
          자동 갱신됩니다.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-4 space-y-3">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <h2 className="text-base font-semibold tracking-tight">
          📍 이번 주 책 진입 자리 (top {limit})
        </h2>
        <span className="text-xs text-muted-foreground">
          7일 내 fire / strength 내림차순 / 종목당 1회 표시
        </span>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs uppercase text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left py-1.5 pr-2">순위</th>
              <th className="text-left py-1.5 px-2">종목</th>
              <th className="text-left py-1.5 px-2">신호</th>
              <th className="text-right py-1.5 px-2">강도</th>
              <th className="text-right py-1.5 px-2">SL</th>
              <th className="text-left py-1.5 pl-2">발생</th>
            </tr>
          </thead>
          <tbody>
            {spots.map((s, i) => {
              const lbl = labelFor(s.signal_type);
              const slOn = SL_ON_PREFERRED.has(s.signal_type);
              return (
                <tr key={s.ticker} className="border-b border-border/40 last:border-0">
                  <td className="py-2 pr-2 text-muted-foreground">{i + 1}</td>
                  <td className="px-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(s.ticker)}?from=dashboard`}
                      className="hover:underline"
                    >
                      <span className="font-mono text-xs">{s.ticker}</span>
                      {s.ticker_name && (
                        <span className="ml-1.5 font-medium">{s.ticker_name}</span>
                      )}
                    </Link>
                  </td>
                  <td className="px-2">{lbl.label}</td>
                  <td className="text-right px-2 font-semibold">
                    {s.strength.toFixed(2)}
                  </td>
                  <td className="text-right px-2">
                    <span className={
                      slOn
                        ? "text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded text-xs"
                        : "text-zinc-700 dark:text-zinc-300 bg-zinc-500/10 px-1.5 py-0.5 rounded text-xs"
                    }>
                      {slOn ? "10%" : "OFF"}
                    </span>
                  </td>
                  <td className="pl-2 text-xs text-muted-foreground whitespace-nowrap">
                    {new Date(s.detected_at).toLocaleDateString("ko-KR", {
                      month: "numeric", day: "numeric",
                    })}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-muted-foreground leading-relaxed">
        Universe-honest production config — no-SL / max=50 / 24w hold /
        top-5 entries (CAGR 13.4% / Sharpe 0.62 / DD 47.6%). Top {limit}만
        표시. SL 컬럼 = 신호별 stop-loss 추천 (volume_case_3 + action_strong_buy
        만 ON 권장 — sweep_per_signal_sl 결과). 실제 매매는 본인 책임.
      </div>
    </section>
  );
}
