/**
 * Recommendations — reads from Supabase `scan_results` (populated by the
 * `python -m app.db.scan_daily` cron). No live backend round-trip.
 *
 * Filters via querystring:
 *   ?market=KOSPI|KOSDAQ|NASDAQ|all   (default: all)
 *   ?signal=action|pattern|all        (default: action — overall recos)
 *   ?min_strength=0.7                 (default 0.7)
 *   ?top=50                            (default 50)
 */
import Link from "next/link";
import { ActionBadge } from "@/components/action-badge";
import { formatNumber } from "@/lib/utils";
import { getServerClient, type ScanResultRow } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface SearchParams {
  market?: string;
  signal?: string;
  min_strength?: string;
  top?: string;
}

type ActionType = "STRONG_BUY" | "BUY" | "SELL" | "SELL_OR_SHORT" | "AVOID" | "HOLD";

const ACTION_BY_SIGNAL: Record<string, ActionType> = {
  action_strong_buy: "STRONG_BUY",
  action_buy: "BUY",
  action_sell: "SELL",
  action_sell_short: "SELL_OR_SHORT",
  action_avoid: "AVOID",
};

type Row = ScanResultRow & {
  name?: string | null;
  market?: string | null;
};

async function fetchRecommendations(
  market: string,
  signalKind: string,
  minStrength: number,
  top: number,
): Promise<{ items: Row[]; total: number; error: string | null }> {
  try {
    const sb = getServerClient();
    let q = sb
      .from("scan_results")
      .select(
        "id, ticker, signal_type, timeframe, detected_at, strength, reason, params, " +
        "tickers:ticker(name, market)",
        { count: "exact" },
      )
      .eq("is_active", true)
      .gte("strength", minStrength)
      .order("strength", { ascending: false })
      .limit(top);

    if (signalKind === "action") {
      q = q.like("signal_type", "action_%");
    } else if (signalKind === "pattern") {
      q = q.like("signal_type", "pattern_%");
    } else if (signalKind === "buy") {
      q = q.in("signal_type", ["action_strong_buy", "action_buy"]);
    }

    const { data, count, error } = await q;
    if (error) return { items: [], total: 0, error: error.message };

    let items = (data ?? []).map((rawRow) => {
      const r = rawRow as unknown as ScanResultRow & {
        tickers?: { name?: string; market?: string } | null;
      };
      return {
        ...r,
        name: r.tickers?.name ?? null,
        market: r.tickers?.market ?? null,
      } as Row;
    });

    if (market !== "all") {
      items = items.filter((r) => r.market === market);
    }

    return { items, total: count ?? items.length, error: null };
  } catch (e) {
    return { items: [], total: 0, error: String(e) };
  }
}

function actionFor(signalType: string): ActionType {
  return ACTION_BY_SIGNAL[signalType] ?? "HOLD";
}

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const market = sp.market ?? "all";
  const signalKind = sp.signal ?? "buy";
  const minStrength = Number(sp.min_strength ?? 0.7);
  const top = Number(sp.top ?? 50);

  const { items, total, error } = await fetchRecommendations(
    market,
    signalKind,
    minStrength,
    top,
  );

  return (
    <div className="space-y-6 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            추천 종목
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매일 16시 책 17종 기법 자동 스캔.{" "}
            <span className="font-mono">강도 ≥ {minStrength.toFixed(2)}</span> 만 표시.
          </p>
        </div>
      </header>

      <form className="flex flex-wrap items-end gap-3" method="GET">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">시장</label>
          <select
            name="market"
            defaultValue={market}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm"
          >
            <option value="all">전체</option>
            <option value="KOSPI">KOSPI</option>
            <option value="KOSDAQ">KOSDAQ</option>
            <option value="NASDAQ">US (S&amp;P 500)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">신호 유형</label>
          <select
            name="signal"
            defaultValue={signalKind}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm"
          >
            <option value="buy">매수 신호 (BUY/STRONG_BUY)</option>
            <option value="action">전체 종합 액션</option>
            <option value="pattern">패턴 완성</option>
            <option value="all">전체</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">최소 강도</label>
          <select
            name="min_strength"
            defaultValue={String(minStrength)}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm"
          >
            <option value="0.5">0.50</option>
            <option value="0.7">0.70 (권장)</option>
            <option value="0.85">0.85 (엄격)</option>
            <option value="0.95">0.95 (최강만)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Top N</label>
          <select
            name="top"
            defaultValue={String(top)}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm"
          >
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
          </select>
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 transition"
        >
          새로고침
        </button>
      </form>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm">
          <div className="font-medium text-rose-700 dark:text-rose-300">
            추천 불러오기 실패
          </div>
          <div className="mt-2 font-mono text-xs text-rose-700/80 dark:text-rose-200/80">
            {error}
          </div>
        </div>
      ) : (
        <>
          <div className="text-xs text-muted-foreground">
            전체 {total}개 매치 · 상위 {items.length}개 표시
          </div>

          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium text-muted-foreground">#</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">티커</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">종목명</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">시장</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">액션</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">강도</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">TF</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">이유</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => {
                  const action = actionFor(it.signal_type);
                  return (
                    <tr
                      key={it.id}
                      className="border-t border-border hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-3 py-2 text-muted-foreground text-xs">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">
                        <Link
                          href={`/stocks/${encodeURIComponent(it.ticker)}`}
                          className="hover:underline"
                        >
                          {it.ticker}
                        </Link>
                      </td>
                      <td className="px-3 py-2">{it.name ?? "—"}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {it.market ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        {action !== "HOLD" ? (
                          <ActionBadge action={action} size="sm" />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {it.signal_type.replace(/^pattern_|^volume_|^retracement_/, "")}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {it.strength != null ? it.strength.toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {it.timeframe}
                      </td>
                      <td className="px-3 py-2 text-xs">{it.reason ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {items.length === 0 && (
              <div className="py-12 text-center text-muted-foreground text-sm">
                조건을 만족하는 신호가 없습니다. 강도 기준을 낮춰보거나 시장을 바꿔보세요.
                {formatNumber(0)/* keeps util in use */}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
