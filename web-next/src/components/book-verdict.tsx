/**
 * Top-of-page one-line verdict. The detail page below this card carries
 * the supporting evidence (trend tiles, patterns, volume case, entry plan)
 * but the user shouldn't have to synthesise that themselves to make a
 * decision. This component does the synthesis in plain Korean.
 *
 * Logic priority (matches the book's signal hierarchy):
 *   1. AVOID / SELL_OR_SHORT / SELL — show the bearish verdict
 *   2. STRONG_BUY / BUY with FRESH bullish pattern — "지금 진입 자리"
 *   3. STRONG_BUY / BUY with STALE (>60d) bullish pattern — "추세는 살아있지만
 *      매수 자리는 끝났습니다" (the SK텔레콤 case)
 *   4. HOLD or anything else — neutral guidance
 *
 * For Korean tickers the price is formatted in 원 (no decimals); for US
 * in $ with 2 decimals.
 */
import type { AnalysisResult } from "@/lib/types/analysis";

interface Props {
  result: AnalysisResult;
}

/**
 * Pick the "most useful for trading" completed bullish pattern. The
 * pattern's `detected_at` is just "when the scan ran" (not when the
 * pattern formed), so we use **runup since pattern entry** as the real
 * staleness signal: if price has already run +30% past the entry, the
 * breakout has played out and a new buyer would chase.
 */
function pickFreshBullishPattern(
  result: AnalysisResult,
): { kind: string; entry: number; runupPct: number } | null {
  const last = result.last_close;
  let best: { kind: string; entry: number; runupPct: number } | null = null;
  for (const p of result.patterns) {
    if (!p.completed || p.direction !== "bullish") continue;
    if (!p.entry || p.entry <= 0) continue;
    const runup = (last / p.entry - 1) * 100;
    if (!best || runup < best.runupPct) {
      best = { kind: p.kind, entry: p.entry, runupPct: runup };
    }
  }
  return best;
}

function runupBlurb(pct: number): string {
  if (pct < 5)  return "이번 주 진입 자리";
  if (pct < 15) return `진입 대비 +${pct.toFixed(0)}% — 아직 추격 가능`;
  if (pct < 30) return `진입 대비 +${pct.toFixed(0)}% — 일부 진입 자리 지남`;
  return `진입 대비 +${pct.toFixed(0)}% — 매수 자리는 이미 끝났습니다`;
}

function formatPrice(v: number, ticker: string): string {
  const isUS = !/\.KS$|\.KQ$/.test(ticker);
  if (isUS) return `$${v.toFixed(2)}`;
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function BookVerdict({ result }: Props) {
  const r = result;
  const monthly = r.trend.monthly;
  const weekly = r.trend.weekly;
  const last = r.last_close;
  const ticker = r.ticker;
  const warnings = collectWarnings(r);

  // ── BEARISH branches ─────────────────────────────────────────────
  if (r.action === "AVOID") {
    return verdictCard("rose", "🔴", "회피", [
      "월봉 240MA 아래 — 책의 죽은 차트.",
      "신규 매수 금지. 추세가 240MA 위로 다시 올라설 때까지 관망.",
    ], warnings);
  }
  if (r.action === "SELL_OR_SHORT" || r.action === "SELL") {
    const ma10 = monthly?.ma_10 ?? weekly?.ma_10;
    const lines = [
      monthly && monthly.above_ma_10 === false
        ? "월봉 10MA 하향 이탈 — 책의 청산 신호."
        : "주봉 10MA 이탈 또는 약세 패턴 발현.",
      ma10
        ? `보유 중이면 즉시 청산. 재진입은 ${formatPrice(ma10, ticker)} 회복 + 양봉 마감 확인 후.`
        : "보유 중이면 즉시 청산.",
    ];
    return verdictCard("rose", "🔴", r.action === "SELL_OR_SHORT" ? "청산/인버스" : "매도", lines, warnings);
  }

  // ── BULLISH branches ────────────────────────────────────────────
  if (r.action === "BUY" || r.action === "STRONG_BUY") {
    const pat = pickFreshBullishPattern(r);
    const ma240 = weekly?.ma_240 ?? null;
    const above240Pct =
      ma240 && ma240 > 0 ? (last / ma240 - 1) * 100 : null;

    // STALE pattern — the SK텔레콤 case (price has run far past the
    // pattern's entry, so a new buyer would be chasing).
    if (pat && pat.runupPct > 30) {
      const lines = [
        `${pat.kind} 매수 자리는 이미 ${pat.runupPct.toFixed(0)}% 위 — 진입가 ${formatPrice(pat.entry, ticker)} 에서 현재 ${formatPrice(last, ticker)} 까지 올랐습니다.`,
        above240Pct != null && above240Pct > 50
          ? `현재가는 주봉 240MA(${formatPrice(ma240!, ticker)}) 대비 +${above240Pct.toFixed(0)}% 위 — 신규 매수 진입 영역에서 멀리 벗어남.`
          : "추세는 아직 살아있지만 신규 매수보다는 보유 평가용입니다.",
        monthly?.ma_10
          ? `보유 중이면 월봉 10MA(${formatPrice(monthly.ma_10, ticker)}) 이탈 시 청산.`
          : "보유 중이면 추세 이탈 시 청산.",
      ];
      return verdictCard("amber", "⚠️", "추세 유효 · 진입 자리 지남", lines, warnings);
    }

    // FRESH or no-pattern bullish — true entry zone.
    const lines: string[] = [];
    if (pat) {
      lines.push(`${pat.kind} 패턴 완성 — ${runupBlurb(pat.runupPct)}.`);
    } else {
      lines.push("다중 시간프레임 정렬 + 추세 지표 우호.");
    }
    if (r.entry_plan && r.entry_plan.entry != null) {
      const ep = r.entry_plan;
      const entryV = ep.entry as number;
      const stopPct =
        ep.stop != null ? ((ep.stop / entryV) - 1) * 100 : null;
      const targetPct =
        ep.target != null ? ((ep.target / entryV) - 1) * 100 : null;
      const bits = [
        `진입 ${formatPrice(entryV, ticker)}`,
        ep.stop != null && stopPct != null
          ? `손절 ${formatPrice(ep.stop, ticker)} (${stopPct.toFixed(1)}%)`
          : null,
        ep.target != null && targetPct != null
          ? `목표 ${formatPrice(ep.target, ticker)} (+${targetPct.toFixed(0)}%)`
          : null,
      ].filter(Boolean).join(" · ");
      lines.push(bits);
    }
    return verdictCard("emerald", "🟢", r.action === "STRONG_BUY" ? "강한 매수" : "매수", lines, warnings);
  }

  // ── HOLD / fallback ─────────────────────────────────────────────
  return verdictCard("zinc", "🟡", "관망", [
    "추세는 유효하나 명확한 진입 신호 부족.",
    monthly?.ma_10
      ? `월봉 10MA(${formatPrice(monthly.ma_10, ticker)}) 위에서 추세 확인 시 매수 진입.`
      : "추세 확인 후 진입.",
  ], warnings);
}

/**
 * Walks the analyzer output looking for internal dissonances that the
 * single-number `book_score` glosses over — the kinds of things a
 * careful reader would call out in a peer review of the recommendation.
 * Examples:
 *   - action is bullish but the volume case is distribution
 *     (case 8/9/10: "분배 의심", "세력 위임")
 *   - action is bullish but the last candle is a doji / inverted hammer
 *     (price refused to follow through)
 *   - the monthly 240MA gate can't be computed (insufficient history)
 *   - current price is >50% above weekly 240MA (entry zone long passed)
 */
function collectWarnings(r: AnalysisResult): string[] {
  const out: string[] = [];
  const bullishAction = r.action === "BUY" || r.action === "STRONG_BUY";

  // Volume vs action dissonance
  if (bullishAction && r.volume_case) {
    const dir = r.volume_case.direction;
    const label = r.volume_case.label_kr ?? "";
    if (dir === "bearish") {
      out.push(`거래량은 ${label} — 매수 신호와 어긋남.`);
    }
  }

  // Last-candle weakness on a bullish call
  if (bullishAction && r.last_candle) {
    const lc = r.last_candle;
    const isDoji = lc.body_pct < 0.3;
    if (!lc.is_bullish && lc.upper_wick_pct > 0.3) {
      out.push("마지막 캔들이 위꼬리 음봉 — 단기 매도 압력.");
    } else if (isDoji) {
      out.push("마지막 캔들이 도지 — 매수/매도 균형, 결정 못함.");
    } else if (lc.tags?.includes("눈썹캔들")) {
      out.push("마지막 캔들이 눈썹캔들 — 위·아래 모두 거부.");
    }
  }

  // 240MA gate missing (insufficient monthly history)
  if (bullishAction && r.trend.monthly && r.trend.monthly.ma_240 == null) {
    out.push("월봉 240MA 미계산 — 책의 핵심 안전 게이트 누락 (장기 차트 부족).");
  }

  // Price runaway above 240MA
  if (bullishAction && r.trend.weekly?.ma_240) {
    const pct = (r.last_close / r.trend.weekly.ma_240 - 1) * 100;
    if (pct > 80) {
      out.push(`주봉 240MA 대비 +${pct.toFixed(0)}% — 신규 매수 영역 멀리 벗어남.`);
    }
  }

  return out;
}

function verdictCard(
  tone: "emerald" | "amber" | "rose" | "zinc",
  icon: string,
  title: string,
  lines: string[],
  warnings: string[] = [],
) {
  const colorMap = {
    emerald: "border-emerald-500/40 bg-emerald-500/5 text-emerald-900 dark:text-emerald-100",
    amber:   "border-amber-500/40   bg-amber-500/5   text-amber-900   dark:text-amber-100",
    rose:    "border-rose-500/40    bg-rose-500/5    text-rose-900    dark:text-rose-100",
    zinc:    "border-border         bg-card          text-foreground",
  };
  return (
    <section className={`rounded-lg border-2 ${colorMap[tone]} p-4 space-y-3`}>
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-lg">{icon}</span>
          <h2 className="text-sm font-semibold uppercase tracking-wider">한 줄 평 · {title}</h2>
        </div>
        <div className="space-y-1.5 text-sm leading-relaxed">
          {lines.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
      </div>
      {warnings.length > 0 && (
        <div className="border-t border-current/15 pt-3 space-y-1 text-xs leading-relaxed opacity-90">
          <div className="text-[10px] uppercase tracking-wider opacity-70 mb-1">⚠ 주의</div>
          {warnings.map((w, i) => (
            <p key={i}>· {w}</p>
          ))}
        </div>
      )}
    </section>
  );
}
