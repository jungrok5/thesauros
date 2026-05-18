/**
 * Recommendations — surface the BOOK information that the old single-column
 * "STRONG_BUY (book_score=1.00)" row hid: which specific patterns fired,
 * how the monthly/weekly/daily trend stack lines up, what fraction of the
 * book_score comes from trend vs pattern vs volume, when the signal was
 * detected (NEW <24h), and what the chart actually looks like (sparkline).
 *
 * Filters via querystring:
 *   ?market=KOSPI|KOSDAQ|all   (default: all)
 *   ?signal=buy|action|pattern|all   (default: buy)
 *   ?min_strength=0.7   ?top=50   ?sort=strength|ticker|name
 */
import Link from "next/link";
import { ActionBadge } from "@/components/action-badge";
import { HelpTip } from "@/components/help-tip";
import { PatternChips, type PatternBlock } from "@/components/pattern-chips";
import { MultiTFMatrix } from "@/components/multi-tf-matrix";
import { ScoreBreakdown } from "@/components/score-breakdown";
import { NewBadge } from "@/components/new-badge";
import { Sparkline } from "@/components/sparkline";
import { getServerClient, type ScanResultRow } from "@/lib/supabase";
import {
  BEARISH_PATTERN_KEYS,
  BULLISH_PATTERN_KEYS,
  directionStyle,
  labelFor,
} from "@/lib/signal-labels";

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

interface TrendState {
  label?: string | null;
  above_ma_10?: boolean | null;
  above_ma_240?: boolean | null;
  alignment_score?: number | null;
  overall_score?: number | null;
}

interface AnalyzeResultBlob {
  trend?: {
    daily?: TrendState | null;
    weekly?: TrendState | null;
    monthly?: TrendState | null;
    book_signal?: string;
    book_reason?: string;
  } | null;
  patterns?: PatternBlock[];
  volume_case?: {
    case?: number;
    label_kr?: string;
    direction?: string;
    confidence?: number;
  } | null;
  book_score?: number;
}

type ScanParams = {
  book_score?: number;
  trend_signal?: string;
  last_close?: number;
  kind?: string;
  confidence?: number;
  timeframe?: string;
};

type Row = ScanResultRow & {
  name?: string | null;
  market?: string | null;
  params?: ScanParams | null;
  analyze?: AnalyzeResultBlob | null;
  recent_closes?: number[];
};

function actionFor(signalType: string): ActionType {
  return ACTION_BY_SIGNAL[signalType] ?? "HOLD";
}

/**
 * Best-effort decomposition of `book_score` into trend / pattern / volume
 * sub-scores. The current analyzer doesn't store these separately, so we
 * recover approximations from the rich `analyze_results.result` fields.
 */
function decomposeScore(a: AnalyzeResultBlob | null | undefined): {
  trend: number | null;
  pattern: number | null;
  volume: number | null;
} {
  if (!a) return { trend: null, pattern: null, volume: null };
  const tParts = [
    a.trend?.monthly?.overall_score,
    a.trend?.weekly?.overall_score,
    a.trend?.daily?.overall_score,
  ].filter((x): x is number => typeof x === "number");
  const trend = tParts.length ? tParts.reduce((s, v) => s + v, 0) / tParts.length : null;

  const bullish = (a.patterns ?? []).filter(
    (p) => p.direction === "bullish" && p.completed !== false,
  );
  const pattern = bullish.length
    ? Math.min(1, bullish.reduce((s, p) => s + (p.confidence ?? 0), 0) / 2)
    : null;

  const vc = a.volume_case;
  const volume = vc?.confidence != null
    ? (vc.direction === "bullish" ? vc.confidence
       : vc.direction === "bearish" ? -vc.confidence
       : vc.confidence * 0.5)
    : null;

  return { trend, pattern, volume };
}

function humanReason(it: Row): string {
  // Pattern + volume signals: the signal IS the reason, so prefer the
  // pattern-specific phrase rather than the multi-TF trend narrative.
  if (
    it.signal_type.startsWith("pattern_") ||
    it.signal_type.startsWith("volume_")
  ) {
    const conf = it.params?.confidence;
    const confStr = typeof conf === "number"
      ? ` · 신뢰도 ${(conf * 100).toFixed(0)}%`
      : "";
    return `${labelFor(it.signal_type).phrase} 완성${confStr}`;
  }
  // Action signals: prefer the analyzer's narrative reason since it
  // already explains why the multi-TF stack gave a BUY/SELL.
  const reason = it.analyze?.trend?.book_reason;
  if (reason) return reason;
  const score = it.analyze?.book_score ?? it.params?.book_score;
  const scoreStr = typeof score === "number"
    ? ` · 종합점수 ${score >= 0 ? "+" : ""}${score.toFixed(2)}`
    : "";
  return `${labelFor(it.signal_type).phrase}${scoreStr}`;
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

    if (sort === "ticker") q = q.order("ticker", { ascending: true });
    else q = q.order("strength", { ascending: false });

    if (signalKind === "action") q = q.like("signal_type", "action_%");
    else if (signalKind === "bullish_pattern") q = q.in("signal_type", BULLISH_PATTERN_KEYS);
    else if (signalKind === "bearish_pattern") q = q.in("signal_type", BEARISH_PATTERN_KEYS);
    else if (signalKind === "pattern") q = q.like("signal_type", "pattern_%");
    else if (signalKind === "buy") q = q.in("signal_type", ["action_strong_buy", "action_buy"]);

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

    // Bulk-fetch analyze_results + recent weekly closes for the visible set.
    const tickers = items.map((r) => r.ticker);
    if (tickers.length) {
      const [ar, bars] = await Promise.all([
        sb.from("analyze_results").select("ticker, result").in("ticker", tickers),
        sb
          .from("bars")
          .select("ticker, bar_date, close")
          .in("ticker", tickers)
          .eq("granularity", "W")
          .order("bar_date", { ascending: true }),
      ]);
      const analyzeByTicker = new Map<string, AnalyzeResultBlob>();
      for (const row of ar.data ?? []) {
        analyzeByTicker.set(
          (row as { ticker: string }).ticker,
          (row as { result: AnalyzeResultBlob }).result,
        );
      }
      const closesByTicker = new Map<string, number[]>();
      for (const row of bars.data ?? []) {
        const t = (row as { ticker: string }).ticker;
        const c = Number((row as { close: number }).close);
        if (!Number.isFinite(c)) continue;
        const arr = closesByTicker.get(t) ?? [];
        arr.push(c);
        closesByTicker.set(t, arr);
      }
      items = items.map((it) => ({
        ...it,
        analyze: analyzeByTicker.get(it.ticker) ?? null,
        recent_closes: (closesByTicker.get(it.ticker) ?? []).slice(-60),
      }));
    }

    return { items, total: count ?? items.length, error: null };
  } catch (e) {
    return { items: [], total: 0, error: String(e) };
  }
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
    market, signalKind, minStrength, top, sort,
  );

  return (
    <div className="space-y-6 max-w-7xl">
      <header className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">추천 종목</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매주 금요일 17시 KST 자동 스캔 — 주봉 기반 추세 + 17종 패턴 + 거래량.{" "}
            <span className="font-mono">강도 ≥ {minStrength.toFixed(2)}</span> 만 표시.
          </p>
        </div>
      </header>

      <form className="flex flex-wrap items-end gap-3" method="GET">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">시장</label>
          <select name="market" defaultValue={market}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm">
            <option value="all">전체</option>
            <option value="KOSPI">KOSPI</option>
            <option value="KOSDAQ">KOSDAQ</option>
            <option value="NASDAQ">US (watchlist)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">신호 유형</label>
          <select name="signal" defaultValue={signalKind}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm">
            <option value="buy">매수 액션 (강한 매수 / 매수)</option>
            <option value="bullish_pattern">매수 패턴 (쌍바닥 · 역H&amp;S · 컵핸들)</option>
            <option value="bearish_pattern">매도 패턴 (이중천장 · H&amp;S)</option>
            <option value="action">전체 종합 액션 (매수/매도/회피 모두)</option>
            <option value="pattern">전체 패턴 (매수+매도 섞임)</option>
            <option value="all">전체 신호</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">최소 강도</label>
          <select name="min_strength" defaultValue={String(minStrength)}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm">
            <option value="0.5">0.50</option>
            <option value="0.7">0.70 (권장)</option>
            <option value="0.85">0.85 (엄격)</option>
            <option value="0.95">0.95 (최강만)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">정렬</label>
          <select name="sort" defaultValue={sort}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm">
            <option value="strength">강도 (높은 순)</option>
            <option value="ticker">티커 (가나다)</option>
            <option value="name">종목명 (가나다)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Top N</label>
          <select name="top" defaultValue={String(top)}
            className="px-3 py-2 rounded-md border border-input bg-background text-sm">
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
          </select>
        </div>
        <button type="submit"
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 transition">
          새로고침
        </button>
      </form>

      <div className="text-xs text-muted-foreground rounded-md border border-border bg-muted/30 px-3 py-2 space-y-1">
        <div>
          <strong>강도</strong>: 0.00–1.00 종합 신뢰도. <strong>추/패/거</strong>: 추세·패턴·거래량
          sub-score (각 0-1). <strong>월/주/일</strong>: 시간프레임별 추세 정렬 (↑ 강세, → 중립,
          ↓/✕ 약세). <strong>NEW</strong>: 30시간 이내 새로 잡힌 신호.
        </div>
        <div>
          <strong>패턴 색상</strong>:
          <span className="ml-1 px-1.5 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">초록 = 매수 패턴</span>
          {" "}
          <span className="px-1.5 py-0.5 rounded border border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300">빨강 = 매도 패턴</span>
          {" "}쌍바닥·역H&amp;S는 매수 반전, 이중천장·H&amp;S는 매도 반전. 신호 유형 필터로 분리해서 보기 권장.
        </div>
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
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-border py-12 text-center text-muted-foreground text-sm">
          조건을 만족하는 신호가 없습니다. 강도 기준을 낮추거나 시장을 바꿔보세요.
        </div>
      ) : (
        <>
          <div className="text-xs text-muted-foreground">
            전체 {total}개 매치 · 상위 {items.length}개 표시
          </div>

          {/* Mobile: rich card stack */}
          <ul className="md:hidden space-y-3">
            {items.map((it, i) => {
              const action = actionFor(it.signal_type);
              const sub = decomposeScore(it.analyze);
              const patterns = it.analyze?.patterns ?? [];
              const tr = it.analyze?.trend;
              return (
                <li key={it.id} className="rounded-lg border border-border bg-card p-3 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Link href={`/stocks/${encodeURIComponent(it.ticker)}`}
                          className="font-mono text-base hover:underline truncate">
                          {it.ticker}
                        </Link>
                        <span className="text-xs text-muted-foreground">{it.market ?? "—"}</span>
                        <NewBadge detectedAt={it.detected_at} />
                      </div>
                      <div className="text-sm font-medium truncate">{it.name ?? "—"}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      {action !== "HOLD" ? (
                        <div className="flex items-center gap-1">
                          <ActionBadge action={action} size="sm" />
                          <HelpTip term={ACTION_TERM[action]} />
                        </div>
                      ) : (() => {
                        const lbl = labelFor(it.signal_type);
                        const s = directionStyle(lbl.direction);
                        return (
                          <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${s.bg} ${s.text} ${s.border}`}>
                            {lbl.label}
                          </span>
                        );
                      })()}
                      <span className="text-[10px] font-mono text-muted-foreground">
                        강도 {it.strength != null ? it.strength.toFixed(2) : "—"}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <MultiTFMatrix
                      monthly={tr?.monthly}
                      weekly={tr?.weekly}
                      daily={tr?.daily}
                    />
                    <Sparkline closes={it.recent_closes ?? []} width={120} height={28} />
                  </div>
                  <ScoreBreakdown
                    trend={sub.trend}
                    pattern={sub.pattern}
                    volume={sub.volume}
                  />
                  {patterns.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <PatternChips patterns={patterns} max={4} />
                    </div>
                  )}
                  <p className="text-[10px] text-muted-foreground/90">{humanReason(it)}</p>
                  <div className="text-[10px] text-muted-foreground/60 text-right">#{i + 1}</div>
                </li>
              );
            })}
          </ul>

          {/* Desktop: wide row table */}
          <div className="hidden md:block rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-2 py-2 font-medium text-muted-foreground w-8">#</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">종목</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">액션 · 강도</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">월/주/일</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">패턴</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">추 · 패 · 거</th>
                  <th className="px-2 py-2 font-medium text-muted-foreground">차트</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => {
                  const action = actionFor(it.signal_type);
                  const sub = decomposeScore(it.analyze);
                  const patterns = it.analyze?.patterns ?? [];
                  const tr = it.analyze?.trend;
                  return (
                    <tr key={it.id} className="border-t border-border hover:bg-muted/20 align-top">
                      <td className="px-2 py-2 text-muted-foreground text-xs">{i + 1}</td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Link href={`/stocks/${encodeURIComponent(it.ticker)}`}
                              className="font-mono text-sm hover:underline">
                              {it.ticker}
                            </Link>
                            <NewBadge detectedAt={it.detected_at} />
                          </div>
                          <span className="text-xs">{it.name ?? "—"}</span>
                          <span className="text-[10px] text-muted-foreground">{it.market ?? "—"}</span>
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-1.5">
                          {action !== "HOLD" ? (
                            <>
                              <ActionBadge action={action} size="sm" />
                              <HelpTip term={ACTION_TERM[action]} />
                            </>
                          ) : (() => {
                            const lbl = labelFor(it.signal_type);
                            const s = directionStyle(lbl.direction);
                            return (
                              <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${s.bg} ${s.text} ${s.border}`}>
                                {lbl.label}
                              </span>
                            );
                          })()}
                          <span className="text-[11px] font-mono text-muted-foreground">
                            {it.strength != null ? it.strength.toFixed(2) : "—"}
                          </span>
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <MultiTFMatrix
                          monthly={tr?.monthly}
                          weekly={tr?.weekly}
                          daily={tr?.daily}
                        />
                      </td>
                      <td className="px-2 py-2 max-w-[240px]">
                        <PatternChips patterns={patterns} max={3} />
                      </td>
                      <td className="px-2 py-2">
                        <ScoreBreakdown
                          trend={sub.trend}
                          pattern={sub.pattern}
                          volume={sub.volume}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <Sparkline closes={it.recent_closes ?? []} width={88} height={24} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
