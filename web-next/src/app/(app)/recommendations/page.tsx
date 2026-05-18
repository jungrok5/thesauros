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
import { NewBadge, hoursSince } from "@/components/new-badge";
import { Sparkline } from "@/components/sparkline";
import { InvestorFlowChip, type FlowSummary } from "@/components/investor-flow-chip";
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
  /** "1" to keep only rows where weekly+monthly alignment_score ≥ 0.9 each. */
  aligned?: string;
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
  flow?: FlowSummary | null;
  fresh?: { kind: string; runupPct: number } | null;
};

function actionFor(signalType: string): ActionType {
  return ACTION_BY_SIGNAL[signalType] ?? "HOLD";
}

/**
 * Render the freshness state as a small chip: emerald for fresh (<5%),
 * yellow for chasing zone (5-30%), amber for stale (>30%). The
 * recommendations list otherwise collapses all 1.00-strength rows
 * into a visually identical block; freshness is the single most
 * useful differentiator.
 */
function FreshnessChip({ fresh }: { fresh: Row["fresh"] }) {
  if (!fresh) {
    return (
      <span className="text-[10px] text-muted-foreground/60">신선도 ?</span>
    );
  }
  const r = fresh.runupPct;
  let style: string, label: string;
  if (r < 0) {
    style = "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/40";
    label = `돌파선 아래 ${r.toFixed(0)}%`;
  } else if (r < 5) {
    style = "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/50";
    label = `돌파 +${r.toFixed(0)}% 🟢 신선`;
  } else if (r < 15) {
    style = "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30";
    label = `돌파 +${r.toFixed(0)}% 추격 가능`;
  } else if (r < 30) {
    style = "bg-yellow-500/10 text-yellow-800 dark:text-yellow-300 border-yellow-500/40";
    label = `돌파 +${r.toFixed(0)}% 일부 지남`;
  } else {
    style = "bg-amber-500/15 text-amber-800 dark:text-amber-300 border-amber-500/50";
    label = `돌파 +${r.toFixed(0)}% ⚠ 진입 자리 지남`;
  }
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium ${style}`}
      title={`${fresh.kind} 돌파선 대비 현재가 ${r >= 0 ? "+" : ""}${r.toFixed(1)}%`}
    >
      {label}
    </span>
  );
}

/**
 * Find the freshest completed bullish pattern's distance past its
 * breakout level. A row with runup < 5% is a true "right now" entry;
 * >30% means the breakout has already played out and the user is
 * chasing — these get stale styling + a chip on the card.
 *
 * Pattern's `entry` field is filled with current price when completed,
 * so we use `extra.neckline/rim/ma_240/ma_value` as the real breakout
 * reference.
 */
function freshness(a: AnalyzeResultBlob | null | undefined, lastClose: number):
  { kind: string; runupPct: number } | null
{
  if (!a?.patterns?.length) return null;
  let best: { kind: string; runupPct: number } | null = null;
  for (const p of a.patterns) {
    if (!p.completed || p.direction !== "bullish") continue;
    // Use the REAL breakout level from pattern.extra only — fallback to
    // `p.entry` is misleading because completed patterns set entry =
    // last_close, which makes runup always 0% (false freshness).
    const ex = (p.extra ?? {}) as Record<string, unknown>;
    let bl: number | null = null;
    for (const c of [ex.neckline, ex.rim, ex.ma_240, ex.ma_value]) {
      if (typeof c === "number" && c > 0) { bl = c; break; }
    }
    if (bl == null) continue;
    const runup = (lastClose / bl - 1) * 100;
    // Pick the freshest meaningful pattern. "Fresh" means runup is in
    // the 0–5% sweet spot; we rank by absolute distance from that ideal
    // entry zone, so a +3% pattern beats a +20% pattern beats a -25%
    // pattern (broken) beats a +140% pattern (long gone).
    if (!best || bucketScore(runup) < bucketScore(best.runupPct)) {
      best = { kind: p.kind, runupPct: runup };
    }
  }
  return best;
}

/**
 * Bucket score for freshness — lower = better entry.
 *   0 :  0–5%   true fresh breakout
 *   1 :  5–15%  recent breakout, still chase-able
 *   2 :  15–30% partial entry zone gone
 *   3 :  -10–0% near breakout, may still be valid pullback
 *   4 :  <-10%  broken below pattern level (invalidated)
 *   5 :  >30%   long-gone breakout
 */
function bucketScore(r: number): number {
  if (r >= 0 && r < 5)  return 0;
  if (r >= 5 && r < 15) return 1;
  if (r >= 15 && r < 30) return 2;
  if (r >= -10 && r < 0) return 3;
  if (r < -10) return 4;
  return 5;
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
  alignedOnly: boolean,
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
    } else {
      // Primary: strength DESC. Secondary: most-recent detect first so
      // ties (e.g. 12 names at 0.910) have a deterministic order based
      // on signal recency rather than Postgres's arbitrary insertion
      // order. Tertiary: ticker ASC for stable display across reloads.
      q = q
        .order("strength", { ascending: false })
        .order("detected_at", { ascending: false })
        .order("ticker", { ascending: true });
    }

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

    // Bulk-fetch analyze_results + recent weekly closes + 5d investor flow.
    const tickers = items.map((r) => r.ticker);
    if (tickers.length) {
      const flowSince = new Date(Date.now() - 7 * 86_400_000)
        .toISOString().slice(0, 10);
      const [ar, bars, flow] = await Promise.all([
        sb.from("analyze_results").select("ticker, result").in("ticker", tickers),
        sb
          .from("bars")
          .select("ticker, bar_date, close")
          .in("ticker", tickers)
          .eq("granularity", "W")
          .order("bar_date", { ascending: true }),
        sb
          .from("investor_flow")
          .select("ticker, day, foreign_net, institution_net")
          .in("ticker", tickers)
          .gte("day", flowSince)
          .order("day", { ascending: false }),
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
      const flowByTicker = new Map<string, FlowSummary>();
      for (const row of flow.data ?? []) {
        const t = (row as { ticker: string }).ticker;
        const f = Number((row as { foreign_net: number | null }).foreign_net) || 0;
        const i = Number((row as { institution_net: number | null }).institution_net) || 0;
        const d = (row as { day: string }).day;
        const prev = flowByTicker.get(t);
        flowByTicker.set(t, {
          foreignNet: (prev?.foreignNet ?? 0) + f,
          institutionNet: (prev?.institutionNet ?? 0) + i,
          latestDay: prev?.latestDay ?? d,
        });
      }
      items = items.map((it) => {
        const analyze = analyzeByTicker.get(it.ticker) ?? null;
        const closes = closesByTicker.get(it.ticker) ?? [];
        const lastClose = analyze?.book_score != null
          ? closes[closes.length - 1] ?? 0
          : 0;
        return {
          ...it,
          analyze,
          recent_closes: closes.slice(-60),
          flow: flowByTicker.get(it.ticker) ?? null,
          fresh: lastClose > 0 ? freshness(analyze, lastClose) : null,
        };
      });
    }

    if (alignedOnly) {
      items = items.filter((it) => {
        const w = it.analyze?.trend?.weekly?.alignment_score ?? 0;
        const m = it.analyze?.trend?.monthly?.alignment_score ?? 0;
        return w >= 0.9 && m >= 0.9;
      });
    }

    if (sort === "fresh") {
      items.sort((a, b) => {
        const ar = a.fresh?.runupPct;
        const br = b.fresh?.runupPct;
        // Patterns with no breakout-level info → end of list (we can't
        // tell whether they're fresh or stale).
        if (ar == null && br == null) return 0;
        if (ar == null) return 1;
        if (br == null) return -1;
        const ba = bucketScore(ar);
        const bb = bucketScore(br);
        if (ba !== bb) return ba - bb;
        // Same bucket — break ties on strength (higher first).
        return (Number(b.strength) || 0) - (Number(a.strength) || 0);
      });
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
  const alignedOnly = sp.aligned === "1";

  const { items, total, error } = await fetchRecommendations(
    market, signalKind, minStrength, top, sort, alignedOnly,
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
            <option value="fresh">신선도 (돌파 직후 우선)</option>
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
        <label className="flex items-center gap-2 px-3 py-2 rounded-md border border-input bg-background text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            name="aligned"
            value="1"
            defaultChecked={alignedOnly}
            className="accent-foreground"
          />
          <span>월/주 만점</span>
          <span className="text-[10px] text-muted-foreground">(정렬 ≥ 0.9)</span>
        </label>
        <button type="submit"
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 transition">
          새로고침
        </button>
      </form>

      <div className="text-xs text-muted-foreground rounded-md border border-border bg-muted/30 px-3 py-2 space-y-1">
        <div>
          <strong>강도</strong>: 0.00–1.00 종합 신뢰도. <strong>추/패/거</strong>: 추세·패턴·거래량
          sub-score (각 0-1). <strong>월/주/일</strong>: 시간프레임별 추세 정렬 (↑ 강세, → 중립,
          ↓/✕ 약세).
        </div>
        <div>
          <strong>신선도</strong>: 매수 패턴 돌파선 대비 현재가 위치 —{" "}
          <span className="px-1 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">+0~5% 신선</span>{" "}
          <span className="px-1 rounded bg-yellow-500/10 text-yellow-800 dark:text-yellow-300">+15~30% 일부 지남</span>{" "}
          <span className="px-1 rounded bg-amber-500/15 text-amber-800 dark:text-amber-300">+30% 이상 ⚠ 진입 자리 끝남</span>.
          1.00 만점 동률 종목 중 신선도 낮은 종목이 진짜 새 매수 자리. <strong>&quot;신선도 순&quot; 정렬 권장.</strong>
        </div>
        <div>
          <strong>패턴 색상</strong>:
          <span className="ml-1 px-1 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">초록 매수</span>{" "}
          <span className="px-1 rounded bg-rose-500/10 text-rose-700 dark:text-rose-300">빨강 매도</span>.
          쌍바닥·역H&amp;S는 매수 반전, 이중천장·H&amp;S는 매도 반전.
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
              const isStale = (it.fresh?.runupPct ?? 0) > 30;
              return (
                <li key={it.id} className={`rounded-lg border bg-card p-3 space-y-2 ${
                  isStale ? "border-amber-500/40 bg-amber-500/5" : "border-border"
                }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Link href={`/stocks/${encodeURIComponent(it.ticker)}`}
                          className="font-mono text-base hover:underline truncate">
                          {it.ticker}
                        </Link>
                        <span className="text-xs text-muted-foreground">{it.market ?? "—"}</span>
                        <NewBadge freshHoursAgo={hoursSince(it.detected_at)} />
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
                  <div className="flex flex-wrap gap-1.5">
                    <FreshnessChip fresh={it.fresh} />
                    {it.flow && <InvestorFlowChip flow={it.flow} compact />}
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
                  const isStale = (it.fresh?.runupPct ?? 0) > 30;
                  return (
                    <tr key={it.id} className={`border-t border-border hover:bg-muted/20 align-top ${
                      isStale ? "bg-amber-500/[0.03]" : ""
                    }`}>
                      <td className="px-2 py-2 text-muted-foreground text-xs">{i + 1}</td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Link href={`/stocks/${encodeURIComponent(it.ticker)}`}
                              className="font-mono text-sm hover:underline">
                              {it.ticker}
                            </Link>
                            <NewBadge freshHoursAgo={hoursSince(it.detected_at)} />
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
                        <div className="space-y-1">
                          <PatternChips patterns={patterns} max={3} />
                          <div className="flex flex-wrap gap-1">
                            <FreshnessChip fresh={it.fresh} />
                            {it.flow && <InvestorFlowChip flow={it.flow} compact />}
                          </div>
                        </div>
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
