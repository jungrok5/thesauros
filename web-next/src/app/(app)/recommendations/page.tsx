/**
 * Recommendations — reads from Supabase `scan_results` (populated by the
 * `python -m app.db.scan_daily` cron). No live backend round-trip.
 *
 * Filters via querystring:
 *   ?market=KOSPI|KOSDAQ|NASDAQ|all   (default: all)
 *   ?signal=action|pattern|all        (default: action — overall recos)
 *   ?min_strength=0.7                 (default 0.7)
 *   ?top=50                            (default 50)
 *   ?sort=strength|ticker|name        (default: strength)
 */
import Link from "next/link";
import { ActionBadge } from "@/components/action-badge";
import { HelpTip } from "@/components/help-tip";
import { getServerClient, type ScanResultRow } from "@/lib/supabase";

// Updated daily by scan_daily cron; 60s ISR for the common case.
export const revalidate = 60;

interface SearchParams {
  market?: string;
  signal?: string;
  min_strength?: string;
  top?: string;
  sort?: string;
}

type ActionType = "STRONG_BUY" | "BUY" | "SELL" | "SELL_OR_SHORT" | "AVOID" | "HOLD";

const ACTION_BY_SIGNAL: Record<string, ActionType> = {
  action_strong_buy: "STRONG_BUY",
  action_buy: "BUY",
  action_sell: "SELL",
  action_sell_short: "SELL_OR_SHORT",
  action_avoid: "AVOID",
};

const ACTION_TERM: Record<ActionType, string> = {
  STRONG_BUY: "action_strong_buy",
  BUY: "action_buy",
  AVOID: "action_avoid",
  SELL: "action_sell",
  SELL_OR_SHORT: "action_sell",
  HOLD: "action_hold",
};

type ScanParams = {
  book_score?: number;
  trend_signal?: string;
  last_close?: number;
  kind?: string;
  direction?: string;
  confidence?: number;
  timeframe?: string;
};

type Row = ScanResultRow & {
  name?: string | null;
  market?: string | null;
  params?: ScanParams | null;
};

/**
 * Turn the raw `STRONG_BUY (book_score=+1.00)` reason into a human-readable
 * Korean explanation, using params + signal_type for extra context.
 */
function humanReason(it: Row): string {
  const p = it.params ?? {};
  const score = typeof p.book_score === "number" ? p.book_score : null;
  const scoreStr = score !== null ? ` · 종합점수 ${score >= 0 ? "+" : ""}${score.toFixed(2)}` : "";

  if (it.signal_type === "action_strong_buy") {
    return `여러 시간프레임에서 매수 정렬 + 책 패턴 다중 발현${scoreStr}`;
  }
  if (it.signal_type === "action_buy") {
    return `매수 우호 정렬${scoreStr}`;
  }
  if (it.signal_type === "action_avoid") {
    return `추세 약화 또는 약세 패턴 우세${scoreStr}`;
  }
  if (it.signal_type === "action_sell" || it.signal_type === "action_sell_short") {
    return `매도 시그널${scoreStr}`;
  }
  if (it.signal_type?.startsWith("pattern_")) {
    const kind = p.kind ?? it.signal_type.replace("pattern_", "");
    const conf = typeof p.confidence === "number"
      ? ` · 신뢰도 ${(p.confidence * 100).toFixed(0)}%`
      : "";
    return `${kind} 패턴 완성${conf}`;
  }
  if (it.signal_type?.startsWith("retracement_")) {
    const kind = p.kind ?? "되돌림";
    return `되돌림 ${kind} 완성`;
  }
  // fall back to raw reason
  return it.reason ?? "—";
}

async function fetchRecommendations(
  market: string,
  signalKind: string,
  minStrength: number,
  top: number,
  sort: string,
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
      .limit(top);

    if (sort === "ticker") {
      q = q.order("ticker", { ascending: true });
    } else if (sort === "name") {
      // name is on the joined table — fall back to strength here, sort
      // client-side after fetch
      q = q.order("strength", { ascending: false });
    } else {
      q = q.order("strength", { ascending: false });
    }

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
        params?: ScanParams | null;
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
    if (sort === "name") {
      items.sort((a, b) => (a.name ?? "").localeCompare(b.name ?? "", "ko-KR"));
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
  const sort = sp.sort ?? "strength";

  const { items, total, error } = await fetchRecommendations(
    market,
    signalKind,
    minStrength,
    top,
    sort,
  );

  return (
    <div className="space-y-6 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            추천 종목
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매일 16시 자동 스캔 (추세 + 17종 패턴 + 거래량).{" "}
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
          <label className="block text-xs text-muted-foreground mb-1">정렬</label>
          <select
            name="sort"
            defaultValue={sort}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm"
          >
            <option value="strength">강도 (높은 순)</option>
            <option value="ticker">티커 (가나다)</option>
            <option value="name">종목명 (가나다)</option>
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

      <div className="text-xs text-muted-foreground rounded-md border border-border bg-muted/30 px-3 py-2">
        <strong>강도</strong>: 0.00–1.00 종합 신뢰도.
        매수 신호 강도는 (책 종합점수 × 0.4 + 액션별 기본강도 × 0.6) 으로 산출.
        패턴 신호 강도는 그 패턴 자체의 형성 신뢰도. 0.70 이상이 권장 진입 기준.
      </div>

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

          {items.length === 0 ? (
            <div className="rounded-lg border border-border py-12 text-center text-muted-foreground text-sm">
              조건을 만족하는 신호가 없습니다. 강도 기준을 낮추거나 시장을 바꿔보세요.
            </div>
          ) : (
            <>
              {/* Mobile (<md): card list. Eight columns don't fit a phone
                  width — vertical cards stay readable + tappable. */}
              <ul className="md:hidden space-y-2">
                {items.map((it, i) => {
                  const action = actionFor(it.signal_type);
                  const tfTerm =
                    it.timeframe === "weekly"
                      ? "tf_weekly"
                      : it.timeframe === "monthly"
                        ? "tf_monthly"
                        : "tf_daily";
                  return (
                    <li
                      key={it.id}
                      className="rounded-lg border border-border bg-card p-3"
                    >
                      <div className="flex items-baseline justify-between gap-2 mb-1">
                        <Link
                          href={`/stocks/${encodeURIComponent(it.ticker)}`}
                          className="font-mono text-base hover:underline truncate"
                        >
                          {it.ticker}
                        </Link>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {action !== "HOLD" ? (
                            <>
                              <ActionBadge action={action} size="sm" />
                              <HelpTip term={ACTION_TERM[action]} />
                            </>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              {it.signal_type.replace(/^pattern_|^volume_|^retracement_/, "")}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-sm mb-1">{it.name ?? "—"}</div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>{it.market ?? "—"}</span>
                        <span>
                          강도 <span className="font-mono text-foreground">
                            {it.strength != null ? it.strength.toFixed(2) : "—"}
                          </span>
                        </span>
                        <HelpTip term={tfTerm}>{it.timeframe}</HelpTip>
                        <span className="ml-auto text-[10px]">#{i + 1}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground/90">
                        {humanReason(it)}
                      </p>
                    </li>
                  );
                })}
              </ul>

              {/* Desktop (md+): full table */}
              <div className="hidden md:block rounded-lg border border-border overflow-hidden">
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
                      const tfTerm =
                        it.timeframe === "weekly"
                          ? "tf_weekly"
                          : it.timeframe === "monthly"
                            ? "tf_monthly"
                            : "tf_daily";
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
                              <span className="inline-flex items-center gap-1">
                                <ActionBadge action={action} size="sm" />
                                <HelpTip term={ACTION_TERM[action]} />
                              </span>
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
                            <HelpTip term={tfTerm}>{it.timeframe}</HelpTip>
                          </td>
                          <td className="px-3 py-2 text-xs">{humanReason(it)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
