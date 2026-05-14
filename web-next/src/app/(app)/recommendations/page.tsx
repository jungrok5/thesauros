import { api, type ScreenResponse } from "@/lib/api";
import { ActionBadge } from "@/components/action-badge";
import { formatNumber } from "@/lib/utils";
import Link from "next/link";

export const dynamic = "force-dynamic";

interface SearchParams {
  market?: string;
  min_score?: string;
  top?: string;
}

async function fetchScreen(
  market: "us" | "kr" | "all",
  minScore: number,
  top: number,
): Promise<{ data: ScreenResponse | null; error: string | null }> {
  try {
    const data = await api.screen(market, minScore, top);
    return { data, error: null };
  } catch (e) {
    return { data: null, error: String(e) };
  }
}

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const market = ((sp.market as "us" | "kr" | "all") ?? "us") as
    | "us"
    | "kr"
    | "all";
  const minScore = Number(sp.min_score ?? 0.7);
  const top = Number(sp.top ?? 50);

  const { data, error } = await fetchScreen(market, minScore, top);

  return (
    <div className="space-y-6 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Recommendations
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            책 룰(추세 + 패턴 + 거래량) 기반 자동 스크리닝. 점수{" "}
            <span className="font-mono">≥ {minScore.toFixed(2)}</span> 만 표시.
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
            <option value="us">US (S&amp;P 500)</option>
            <option value="kr">KR (KOSPI/KOSDAQ)</option>
            <option value="all">전체</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">
            최소 점수
          </label>
          <select
            name="min_score"
            defaultValue={String(minScore)}
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
          </select>
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 transition"
        >
          새로 스크리닝
        </button>
      </form>

      {error || !data ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm">
          <div className="font-medium text-rose-700 dark:text-rose-300">
            스크리닝 실패
          </div>
          <div className="mt-2 font-mono text-xs text-rose-700/80 dark:text-rose-200/80">
            {error ?? "no data"}
          </div>
        </div>
      ) : (
        <>
          <div className="text-xs text-muted-foreground">
            전체 {data.total_scanned}개 스캔 · {data.n_candidates}개 후보 · 상위{" "}
            {data.items.length}개 표시
          </div>

          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium text-muted-foreground">#</th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">
                    Ticker
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">
                    Action
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Score
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Close
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">
                    Top Pattern
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">
                    TF
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Conf
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Patterns
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((it, i) => (
                  <tr
                    key={it.ticker}
                    className="border-t border-border hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-3 py-2 text-muted-foreground text-xs">
                      {i + 1}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      <Link
                        href={`/stocks/${encodeURIComponent(it.ticker)}`}
                        className="hover:underline"
                      >
                        {it.ticker}
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      <ActionBadge action={it.action} size="sm" />
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {it.book_score >= 0 ? "+" : ""}
                      {it.book_score.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {formatNumber(it.last_close)}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {it.top_pattern ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {it.top_pattern_timeframe ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-xs font-mono">
                      {it.top_pattern_confidence !== null
                        ? `${(it.top_pattern_confidence * 100).toFixed(0)}%`
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground">
                      {it.n_patterns}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.items.length === 0 && (
              <div className="py-12 text-center text-muted-foreground text-sm">
                조건을 만족하는 종목이 없습니다. 점수 기준을 낮춰보세요.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
