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
import type { ReactNode } from "react";
import type { AnalysisResult } from "@/lib/types/analysis";
import { pickCatalyst } from "@/lib/freshness";

interface Props {
  result: AnalysisResult;
  /** Latest bar close from `bars` table — fresher than
   *  `result.last_close` (which is frozen at the analyzer's run time,
   *  i.e. last Friday 17 KST for KR). Used to surface the gap between
   *  what BookVerdict's narrative was computed on vs the price the
   *  user sees right now, so a "포킹 발사 4,944원 위로 대기" verdict
   *  doesn't mislead when today's 5,300원 already cleared the trigger. */
  currentPrice?: number | null;
  /** Bar date for `currentPrice` (YYYY-MM-DD). Optional companion to
   *  `currentPrice`; rendered in the analysis-vs-now header chip. */
  currentBarDate?: string | null;
  /** `analyze_results.updated_at` ISO timestamp — the actual analyzer
   *  run time, which is what we want in the header chip. Both
   *  `result.as_of` and `result.last_candle.date` are stamped with the
   *  **next** Friday's settlement date by the analyzer (future date in
   *  the middle of a week), so they read as "분석 시점이 미래" to
   *  users. 088350.KS 2026-05-20 reported case proved this:
   *  `as_of=last_candle.date="2026-05-22"` while the analyzer actually
   *  ran at `updated_at="2026-05-20 23:53 KST"`. */
  analyzedAt?: string | null;
}

/** Days between two YYYY-MM-DD strings, ignoring tz (calendar days). */
function daysBetween(fromIso: string, toIso: string): number | null {
  if (!fromIso || !toIso) return null;
  const a = new Date(`${fromIso}T00:00:00Z`).getTime();
  const b = new Date(`${toIso}T00:00:00Z`).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

/** Render a header chip explaining when the analysis was last computed
 *  and how far the current price has moved since — so a stale narrative
 *  doesn't read as live guidance. Adds a one-line "entry_plan은 분석 시점
 *  가격 기준" hint when the gap is large enough (>5 %) to risk a user
 *  chasing the trade at a different price than the analyzer planned. */
function AnalyzedAtChip({
  asOf,
  analyzedClose,
  currentPrice,
  currentBarDate,
  ticker,
}: {
  asOf: string;
  analyzedClose: number;
  currentPrice: number | null | undefined;
  currentBarDate: string | null | undefined;
  ticker: string;
}) {
  const hasFreshPrice =
    typeof currentPrice === "number"
    && currentPrice > 0
    && Math.abs(currentPrice - analyzedClose) > 0.0001;
  const deltaPct = hasFreshPrice
    ? ((currentPrice! / analyzedClose) - 1) * 100
    : 0;
  const days = currentBarDate ? daysBetween(asOf, currentBarDate) : null;
  // Large-gap hint: when price has moved >5 % since the analyzer ran,
  // entry/stop/target numbers shown elsewhere on the page may be off
  // enough that a user "chasing" the trade ends up at a worse R/R than
  // the analyzer's plan. Surface this once, here, instead of as a
  // separate banner up the tree (was redundant with this chip).
  const largeGap = hasFreshPrice && Math.abs(deltaPct) > 5;
  return (
    <div className="text-[11px] text-muted-foreground/80 mb-2 space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span>
          🗓️ <strong className="text-foreground/80">{asOf}</strong> 분석 ·
          종가 <span className="font-mono">{formatPrice(analyzedClose, ticker)}</span>
        </span>
        {hasFreshPrice && (
          <span className="rounded-full border border-current/20 px-1.5 py-0.5 font-mono">
            현재 {formatPrice(currentPrice!, ticker)}
            <span className={deltaPct >= 0 ? "text-emerald-600 dark:text-emerald-300 ml-1" : "text-rose-600 dark:text-rose-300 ml-1"}>
              {deltaPct >= 0 ? "+" : ""}{deltaPct.toFixed(1)}%
            </span>
            {days != null && days >= 1 && (
              <span className="ml-1 opacity-70">· {days}일 전</span>
            )}
          </span>
        )}
      </div>
      {largeGap && (
        <div className="text-[11px] leading-relaxed opacity-80">
          진입/손절/목표 수치는 <strong>분석 시점 종가 기준</strong> —
          최신가가 진입가 ±5 % 안이면 그대로 유효, 너무 멀어졌으면 추격 매수 ✗.
        </div>
      )}
    </div>
  );
}

/** Append a "trigger already cleared since analysis" sentence to a
 *  wait-for-trigger verdict when currentPrice has moved past `trigger`
 *  since the analyzer ran. Returns null when no append is warranted —
 *  caller does the optional spread. */
function triggerClearedNote(
  trigger: number | null | undefined,
  analyzedClose: number,
  currentPrice: number | null | undefined,
  ticker: string,
  label = "트리거",
): string | null {
  if (typeof trigger !== "number" || trigger <= 0) return null;
  if (typeof currentPrice !== "number" || currentPrice <= 0) return null;
  // The analyzer's last_close was at-or-below trigger (otherwise the
  // verdict wouldn't be "대기"); only fire when the fresh price has
  // *crossed* the trigger upward. Allow 0.5% buffer so a wobble at the
  // line doesn't fire spuriously.
  if (!(analyzedClose < trigger * 1.005)) return null;
  if (currentPrice <= trigger) return null;
  const overPct = ((currentPrice / trigger) - 1) * 100;
  return (
    `⚡ 분석 이후 현재가 ${formatPrice(currentPrice, ticker)} > ${label} ` +
    `${formatPrice(trigger, ticker)} (+${overPct.toFixed(1)}%) — ` +
    "이번 주 발사 가능. 이번 주 금요일 종가로 추세 재확인."
  );
}

/**
 * The pattern's `entry` field is filled with `last_close` whenever the
 * detector marks `completed=True` (so the user "enters at current price"
 * for a fresh breakout). That makes `entry == last_close` always when
 * the page renders → naive runup = 0%, breaking the staleness signal.
 *
 * The TRUE breakout level — the price the pattern was actually breaking
 * out from — lives in `extra.neckline` (쌍바닥, 쌍천장, H&S, 역H&S),
 * `extra.rim` (Cup with Handle), or `extra.ma_240` / `extra.ma_value`
 * (240MA breakout, 돌반지). Use that as the freshness reference.
 */
function breakoutLevel(p: AnalysisResult["patterns"][number]): number | null {
  const ex = (p.extra ?? {}) as Record<string, unknown>;
  const candidates = [ex.neckline, ex.rim, ex.ma_240, ex.ma_value];
  for (const c of candidates) {
    if (typeof c === "number" && c > 0) return c;
  }
  // Fall back to the pattern's `entry` if no extra-level info available.
  return p.entry && p.entry > 0 ? p.entry : null;
}

export function pickFreshBullishPattern(
  result: AnalysisResult,
): { kind: string; breakout: number; runupPct: number } | null {
  const last = result.last_close;

  // 2026-05-26 fix: prefer whatever pattern the analyzer's entry_plan
  // chose — that's the book-spirit pick (weekly-first + fake_volume
  // penalty, see app/book/analyzer.py:pattern_sort_key). The old
  // runup-closest local heuristic disagreed with the backend on
  // 000370.KS: backend picked catalyst (weekly clean 0.80) for the
  // entry_plan, frontend headline still narrated 삼중바닥 (the
  // closest-runup pattern). Surface the same pattern in both places.
  const ep = result.entry_plan;
  if (ep && typeof ep.based_on === "string") {
    const kind = ep.based_on.split("(", 1)[0].trim();
    const tfMatch = ep.based_on.match(/\(([^)]+)\)/);
    const tf = tfMatch ? tfMatch[1].trim() : null;
    for (const p of result.patterns) {
      if (!p.completed || p.direction !== "bullish") continue;
      if (p.kind !== kind) continue;
      if (tf && p.timeframe && p.timeframe !== tf) continue;
      const bl = breakoutLevel(p);
      if (bl == null) continue;
      const runup = (last / bl - 1) * 100;
      // Even when honoring entry_plan we keep the negative-runup
      // guardrail — a backend pick whose price has fallen back below
      // its breakout is pattern-invalidation territory and shouldn't
      // be narrated as fresh entry.
      if (runup < 0) continue;
      return { kind: p.kind, breakout: bl, runupPct: runup };
    }
    // Fallthrough: entry_plan exists but the matching pattern isn't
    // in the array, OR its breakout level can't be derived (e.g.,
    // analyzer used the 10MA-fallback path with no underlying pattern).
    // Use the legacy heuristic below.
  }

  let best: { kind: string; breakout: number; runupPct: number } | null = null;
  for (const p of result.patterns) {
    if (!p.completed || p.direction !== "bullish") continue;
    const bl = breakoutLevel(p);
    if (bl == null) continue;
    const runup = (last / bl - 1) * 100;
    // Skip patterns where price has fallen back BELOW the breakout level
    // — that's pattern invalidation territory, not "fresh entry". Surfacing
    // them as fresh produced the 088350.KS bug: 장대양봉 catalyst at
    // breakout 5,390 vs last 5,300 → runup −1.7%, picked as fresher than
    // the +47% 쌍바닥, then narrated as "🟢 강한 매수 — 돌파선 아래 −2%
    // 패턴 무효 가능" (self-contradictory verdict). Real fresh = above the
    // breakout level (small positive buffer for round-off).
    if (runup < 0) continue;
    if (!best || runup < best.runupPct) {
      best = { kind: p.kind, breakout: bl, runupPct: runup };
    }
  }
  return best;
}

function runupBlurb(pct: number): string {
  if (pct < 0)  return `돌파선 아래 ${pct.toFixed(0)}% — 패턴 무효 가능`;
  if (pct < 5)  return "이번 주 진입 자리";
  if (pct < 15) return `돌파 대비 +${pct.toFixed(0)}% — 아직 추격 가능`;
  if (pct < 30) return `돌파 대비 +${pct.toFixed(0)}% — 일부 진입 자리 지남`;
  return `돌파 대비 +${pct.toFixed(0)}% — 매수 자리는 이미 끝났습니다`;
}

function formatPrice(v: number, ticker: string): string {
  const isUS = !/\.KS$|\.KQ$/.test(ticker);
  if (isUS) return `$${v.toFixed(2)}`;
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

export function BookVerdict({
  result,
  currentPrice,
  currentBarDate,
  analyzedAt,
}: Props) {
  const r = result;
  const monthly = r.trend.monthly;
  const weekly = r.trend.weekly;
  const last = r.last_close;
  const ticker = r.ticker;
  const warnings = collectWarnings(r);
  // Prefer `analyzedAt` (analyze_results.updated_at — actual run time).
  // Both `as_of` and `last_candle.date` are future-stamped by the
  // analyzer with the next Friday settlement; using either reads as
  // "분석 시점이 미래" on the page. Truncate ISO timestamp to date.
  const analyzedDate = analyzedAt
    ? analyzedAt.slice(0, 10)
    : (r.last_candle?.date ?? r.as_of);
  const analyzedAtChip = (
    <AnalyzedAtChip
      asOf={analyzedDate}
      analyzedClose={last}
      currentPrice={currentPrice}
      currentBarDate={currentBarDate}
      ticker={ticker}
    />
  );

  // ── BEARISH branches ─────────────────────────────────────────────
  if (r.action === "AVOID") {
    return verdictCard("rose", "🔴", "회피", [
      "월봉 240MA 아래 — 책의 죽은 차트.",
      "신규 매수 금지. 추세가 240MA 위로 다시 올라설 때까지 관망.",
    ], warnings, analyzedAtChip);
  }
  if (r.action === "SELL_OR_SHORT" || r.action === "SELL") {
    const ma10 = monthly?.ma_10 ?? weekly?.ma_10;
    // 저승사자 = 장대음봉 + 주봉 10MA 동시 이탈. The analyzer stamps
    // this in stretch_reason when the gate fires. Surface a dedicated
    // verdict that calls out the candle pattern by name (책 p262).
    const isReaper =
      typeof r.stretch_reason === "string" && /저승사자/.test(r.stretch_reason);
    if (isReaper) {
      const lines = [
        `🔴 저승사자 캔들 — 마지막 봉 장대음봉이 주봉 10MA를 동시에 깬 상태. ${r.stretch_reason}.`,
        "책 p262: 저승사자 = 매도 패턴 완성 시그널. 매수 자리 0%.",
        ma10
          ? `보유 중이면 즉시 청산. 재진입은 ${formatPrice(ma10, ticker)} 회복 + 양봉 마감 확인 후.`
          : "보유 중이면 즉시 청산.",
      ];
      return verdictCard("rose", "🔴", "저승사자 · 청산", lines, warnings, analyzedAtChip);
    }
    const lines = [
      monthly && monthly.above_ma_10 === false
        ? "월봉 10MA 하향 이탈 — 책의 청산 신호."
        : "주봉 10MA 이탈 또는 약세 패턴 발현.",
      ma10
        ? `보유 중이면 즉시 청산. 재진입은 ${formatPrice(ma10, ticker)} 회복 + 양봉 마감 확인 후.`
        : "보유 중이면 즉시 청산.",
    ];
    return verdictCard("rose", "🔴", r.action === "SELL_OR_SHORT" ? "청산/인버스" : "매도", lines, warnings, analyzedAtChip);
  }

  // ── Eligibility downgrade guard (2026-05-26 site review) ────────
  // The analyzer's eligibility field is the canonical verdict (same
  // source the NoviceVerdict and the telegram alert use). When it
  // downgrades a bullish action to CONDITIONAL / WATCH / AVOID, the
  // BookVerdict must NOT then render a 🟢 "강한 매수 진입 2,755원"
  // card alongside — that's how the 339950.KQ contradiction surfaced
  // (1위 종목 yet "조건부 — 매수 X" in the novice card). Defer to
  // the eligibility verdict.
  if (
    r.eligibility
    && (r.action === "BUY" || r.action === "STRONG_BUY")
    && r.eligibility.grade !== "OK"
  ) {
    const tone =
      r.eligibility.grade === "AVOID" ? "rose" :
      r.eligibility.grade === "CONDITIONAL" ? "amber" : "zinc";
    const icon =
      r.eligibility.grade === "AVOID" ? "🔴" :
      r.eligibility.grade === "CONDITIONAL" ? "⚠️" : "🟡";
    const ma10w = weekly?.ma_10 ?? null;
    const lines: string[] = [
      r.eligibility.body,
      ma10w
        ? `보유 중이면 주봉 10MA(${formatPrice(ma10w, ticker)}) 이탈 시 청산.`
        : "보유 중이면 추세 이탈 시 청산.",
      nextDecisionLine(ma10w, ticker),
    ];
    return verdictCard(
      tone as "amber" | "rose" | "zinc",
      icon,
      r.eligibility.headline,
      lines,
      warnings,
      analyzedAtChip,
    );
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
        `${pat.kind} 매수 자리는 이미 ${pat.runupPct.toFixed(0)}% 위 — 돌파선 ${formatPrice(pat.breakout, ticker)} 에서 현재 ${formatPrice(last, ticker)} 까지 올랐습니다.`,
        above240Pct != null && above240Pct > 50
          ? `현재가는 주봉 240MA(${formatPrice(ma240!, ticker)}) 대비 +${above240Pct.toFixed(0)}% 위 — 신규 매수 진입 영역에서 멀리 벗어남.`
          : "추세는 아직 살아있지만 신규 매수보다는 보유 평가용입니다.",
        monthly?.ma_10
          ? `보유 중이면 월봉 10MA(${formatPrice(monthly.ma_10, ticker)}) 이탈 시 청산.`
          : "보유 중이면 추세 이탈 시 청산.",
      ];
      return verdictCard("amber", "⚠️", "추세 유효 · 진입 자리 지남", lines, warnings, analyzedAtChip);
    }

    // ── 랠리 후 조정 (post-rally exhaustion): price within 10 % of
    //    52-week high after a meaningful run-up, now consolidating
    //    with indecision candles / drying volume. Semantically OPPOSITE
    //    of 매복 — 매복 is pre-breakout supply absorption, this is
    //    post-rally distribution risk. GOOGL 2026-05-18 was the test
    //    case: 52w pos 95 %, +16 % over 6 weeks, 그레이브스톤도지
    //    (big upper wick) at the top. Must be checked BEFORE 매복 so
    //    GOOGL doesn't get the wrong narrative.
    if (isPostRallyCaution(r)) {
      const ma5 = weekly?.ma_10;   // page doesn't carry 5MA — use 10MA
      const rally = Math.round((r.rally_8w_pct ?? 0) * 100);
      const pos = Math.round((r.position_in_52w ?? 0) * 100);
      const lcTag = (r.last_candle?.tags ?? []).find((t) =>
        ["그레이브스톤도지", "유성형", "역망치형", "도지", "눈썹캔들"].includes(t),
      );
      const lines = [
        `최근 8주 +${rally}% 랠리 후 52주 신고가 ${pos}% 자리에서 단기 조정.`
        + (lcTag ? ` 마지막 캔들 ${lcTag} — 책: 반전 주의.` : ""),
        "책 표현: 큰 상승 끝의 도지/긴 위꼬리 = 매수세 소진 신호.",
        ma5
          ? `보유 중이면 주봉 10MA(${formatPrice(ma5, ticker)}) 이탈 시 청산 고려. 신규 매수 자리 아님.`
          : "보유 중이면 추세 이탈 시 청산. 신규 매수 자리 아님.",
        "다음 확인: 금요일 종가가 10MA 위 마감하면 추세 유지, 아래면 추세 약화.",
      ];
      return verdictCard("amber", "🟡", "랠리 후 조정 · 반전 주의", lines, warnings, analyzedAtChip);
    }

    // ── 매복 단계 (Ambush / Forking-setup): book's "기간 조정 / 빨래
    //    널기" state — MAs converged, volume drying up, no trigger
    //    candle yet. Even when action says STRONG_BUY (trend is up,
    //    multi-TF alignment 1.0), a new buyer at this stage is
    //    chasing a flat box, not entering a fresh breakout. Surface
    //    as a 🟡 "wait for trigger" verdict before the normal BUY
    //    branch.
    if (isAmbushSetup(r)) {
      const ma10w = weekly?.ma_10;
      const lines = [
        "매복 단계 — 이평선 수렴 + 거래량 감소 + 캔들 결정 못함.",
        "책 표현: 기간 조정 / 빨래 널기. 개미는 뜸 들이다 떨어져 나가는 자리. 지금 매수는 박스권 진입 = 자본 묶임.",
        ma10w
          ? `포킹 발사 (장대양봉 + 거래량 증가)가 ${formatPrice(ma10w, ticker)} 위로 터질 때까지 매복.`
          : "포킹 발사 캔들이 뜰 때까지 매복.",
      ];
      const cleared = triggerClearedNote(
        ma10w ?? null,
        last,
        currentPrice,
        ticker,
        "포킹 트리거",
      );
      if (cleared) lines.push(cleared);
      return verdictCard("amber", "🟡", "매복 · 포킹 대기", lines, warnings, analyzedAtChip);
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
      // Short explainer — 사용자가 숫자만 보고 "어디서 나왔고 뭘 의미해?"
      // 라는 두 질문에 한 줄로 답. based_on 은 analyzer 가 채운 산출 근거.
      const base = ep.based_on ? `근거: ${ep.based_on}. ` : "";
      const tgtMeaning = ep.target != null
        ? " · 목표는 일부 익절 검토 라인 — 추세 살아있으면 보유 유지"
        : " · 10MA 이탈까지 trailing stop 으로 들고 가는 open-ended";
      lines.push(
        `${base}주봉 종가가 손절 아래로 마감 시 청산${tgtMeaning}.`,
      );
    }
    return verdictCard("emerald", "🟢", r.action === "STRONG_BUY" ? "강한 매수" : "매수", lines, warnings, analyzedAtChip);
  }

  // ── HOLD due to late-trend stretch (analyzer downgrade) ─────────
  // The analyzer downgrades BUY/STRONG_BUY to HOLD and stamps
  // stretch_reason when the chart looks like "추세는 살았지만 자리
  // 한참 지남" — RKLB +250% above 240MA, GOOGL post-rally, SK텔레콤
  // chase. Different from the pure pattern-stale branch above (that
  // one runs when action is still BUY): here action is HOLD, no
  // entry_plan, and we want a 매수 자격 X verdict, not the generic
  // "관망" copy.
  if (r.stretch_reason) {
    // 저승사자 is handled in the SELL_OR_SHORT branch above (red card).
    // Here we only handle the HOLD-via-stretch path, with optional
    // "장대음봉" warning that doesn't reach 저승사자's 10MA-break severity.
    const isLongBearish = /장대음봉/.test(r.stretch_reason);
    const ma10w = weekly?.ma_10 ?? null;
    const ma240 = weekly?.ma_240 ?? null;
    const above240Pct =
      ma240 && ma240 > 0 ? (last / ma240 - 1) * 100 : null;
    // Surface a candle-reversal callout when the last bar shows top
    // exhaustion signals — 그레이브스톤도지/유성형/역망치/눈썹/도지
    // OR very large upper wick (>0.5). This preserves the GOOGL-style
    // narrative ("그레이브스톤도지 — 반전 주의") that previously lived
    // in the post-rally-caution branch, which now can't fire because
    // the analyzer stretch gate downgrades action to HOLD first.
    const lcTags = r.last_candle?.tags ?? [];
    const reversalTag = lcTags.find((t) =>
      ["그레이브스톤도지", "유성형", "역망치형", "도지", "눈썹캔들"]
        .includes(t),
    );
    const bigUpperWick =
      (r.last_candle?.upper_wick_pct ?? 0) > 0.5
      && (r.last_candle?.body_pct ?? 1) < 0.3;
    const reversalCandle = reversalTag
      || (bigUpperWick ? "긴 위꼬리 캔들" : null);
    const lines: string[] = [
      isLongBearish
        ? `⚠️ 장대음봉 출현 — 책 룰: 매도 압력. ${r.stretch_reason}.`
        : `추세는 살아있지만 신규 매수 자리는 한참 지남 — ${r.stretch_reason}.`,
    ];
    if (reversalCandle && !isLongBearish) {
      lines.push(
        `마지막 캔들 ${reversalCandle} — 책: 큰 상승 끝의 위꼬리/도지 = 매수세 소진. 반전 주의.`,
      );
    }
    lines.push(
      above240Pct != null && above240Pct > 50
        ? `현재가는 주봉 240MA(${formatPrice(ma240!, ticker)}) 대비 +${above240Pct.toFixed(0)}% 위 — 책의 신규 진입 영역에서 벗어남.`
        : "책 룰: 추세 시작부 +50% 안에서만 신규 매수. 그 위는 보유 평가용.",
    );
    lines.push(
      isLongBearish
        ? ma10w
          ? `보유 중이면 주봉 10MA(${formatPrice(ma10w, ticker)}) 이탈 시 즉시 청산. 그 위면 한 봉 더 관찰.`
          : "보유 중이면 다음 봉 확인 — 추세 이탈 시 청산."
        : ma10w
          ? `보유 중이면 주봉 10MA(${formatPrice(ma10w, ticker)}) 이탈 시 청산 — 그때까지는 추세 유지.`
          : "보유 중이면 추세 이탈 시 청산.",
    );
    lines.push(nextDecisionLine(ma10w, ticker));
    return verdictCard(
      "amber",
      "🟡",
      isLongBearish ? "장대음봉 · 매도 압력" : "추세 유효 · 자리 지남",
      lines,
      warnings,
      analyzedAtChip,
    );
  }

  // ── HOLD / fallback ─────────────────────────────────────────────
  // Generic "no patterns + no clear action" branch used to render one
  // boilerplate sentence. For tickers like IONQ that have a clear
  // catalyst candle in the past + decent trend but no fresh chart
  // pattern, we now narrate the situation with concrete numbers:
  //   - 240MA distance ("죽지 않은 차트" / "죽은 차트" gate)
  //   - latest catalyst's high vs current ("catalyst +X % 위")
  //   - 4등분선 25% absolute level → stop guidance
  //   - 주봉 10MA → trailing stop trigger
  //   - next decision point (weekly close on Friday)
  const lines: string[] = [];
  const ma240 = weekly?.ma_240 ?? null;
  const ma10w = weekly?.ma_10 ?? null;
  const cat = pickCatalyst(r.patterns ?? []);

  if (ma240 && last > ma240) {
    const pct = (last / ma240 - 1) * 100;
    lines.push(
      `주봉 240MA(${formatPrice(ma240, ticker)}) 위 +${pct.toFixed(0)}% — 죽지 않은 차트.`,
    );
  } else if (ma240 && last <= ma240) {
    lines.push(
      `주봉 240MA(${formatPrice(ma240, ticker)}) 아래 — 책 기준 죽은 차트.`,
    );
  } else if (monthly && monthly.ma_240 == null) {
    lines.push("월봉 240MA 미계산 (장기 차트 부족) — 안전 게이트 불완전.");
  }

  if (cat?.extra) {
    const ex = cat.extra as Record<string, unknown>;
    const catClose = typeof ex.catalyst_close === "number" ? ex.catalyst_close : null;
    const q25 = typeof ex.q25 === "number" ? ex.q25 : null;
    const runup = typeof ex.runup_since === "number" ? ex.runup_since : null;
    const bars = typeof ex.bars_since === "number" ? ex.bars_since : null;
    if (catClose != null && runup != null) {
      lines.push(
        `장대양봉 catalyst (${bars != null ? `${bars}주 전` : ""}) ` +
        `진입 ${formatPrice(catClose, ticker)} 대비 현재 +${runup.toFixed(0)}% — ` +
        (runup > 30
          ? "신규 매수 자리는 한참 지났음."
          : runup > 10
            ? "추격 가능 구간이지만 진입 자리는 일부 지남."
            : "catalyst 직후 자리."),
      );
    }
    // 4등분선 zone narrative (book p218-223 — signature mechanic).
    // The analyzer computes quarter_zone from the catalyst's body so
    // we don't have to recompute it here.
    const zone = r.quarter_zone;
    if (zone === "safe75") {
      lines.push("📍 4등분선 75 % 안전지대 — 책: 다음 봉 상승 확률 75 %. 매집 살아있음.");
    } else if (zone === "warn50") {
      lines.push("📍 4등분선 50 %대 — 안전지대 살짝 이탈. 조정 진행 중.");
    } else if (zone === "danger25") {
      lines.push("📍 4등분선 25 ~ 50 % (매입원가 영역) — 책: 적신호.");
    } else if (zone === "broken") {
      lines.push("📍 4등분선 25 % 절대자리 깨짐 — 책: catalyst 부정, 매도 자리.");
    }
    if (q25 != null) {
      lines.push(
        `손절: 장대양봉 25% 절대자리 ${formatPrice(q25, ticker)} 이탈 시 — ` +
        "그 아래는 catalyst 부정.",
      );
    }
  }

  if (ma10w) {
    lines.push(
      `보유 중이면 주봉 10MA(${formatPrice(ma10w, ticker)}) 이탈 시 청산 — 책의 추세 사망 라인.`,
    );
  }

  // Next decision — book mandates Friday 15:30 KST for weekly trades.
  lines.push(nextDecisionLine(ma10w, ticker));

  if (lines.length === 0) {
    // Truly nothing to anchor on
    lines.push("추세 약함, catalyst 없음, 패턴 미발현. 다음 주봉 마감까지 관망.");
  }

  return verdictCard("zinc", "🟡", "관망", lines, warnings, analyzedAtChip);
}

/** Next-decision-point guidance — book's 종가매매 mode (주봉 = 금요일
 *  15:30 KST). We don't try to compute the exact Friday in TZ math
 *  here; the page's MarketHoursNotice already shows the live D-counter. */
function nextDecisionLine(ma10w: number | null | undefined, ticker: string): string {
  if (ma10w) {
    return (
      `📅 다음 결정 시점: 이번 주 금요일 종가. ` +
      `5MA / 10MA(${formatPrice(ma10w, ticker)}) 위 마감이면 추세 유지, ` +
      `아래면 추세 약화 — 청산 검토.`
    );
  }
  return "📅 다음 결정 시점: 이번 주 금요일 종가 확인 후 추세 재판단.";
}

/**
 * Detect the "매복 단계 / Forking setup" state — strong-buy action with
 * the book's accumulation pattern underneath: 이평선 수렴 + 거래량 감소
 * + 결정 못한 캔들 (도지 / 망치 / 눈썹). User shouldn't enter here;
 * they should wait for the trigger candle.
 *
 * Indicators that combine into the verdict:
 *   - volume case 12 (수렴기 거래량 감소) OR volume direction neutral/bull
 *     with vol_ratio interpretation hinting at drying-up
 *   - a `MA 수렴 매복` pattern in the patterns list (from
 *     detect_ma_convergence_setup)
 *   - last candle is small body with single dominant wick (망치 / 교수 /
 *     역망치 / 유성) OR doji / 눈썹 — i.e., indecision
 */
/**
 * Post-rally caution: price near 52-week high after a meaningful run-up,
 * showing a top-reversal candle. The semantic OPPOSITE of 매복:
 *   매복 = pre-breakout supply absorption (mid-range, optimistic setup)
 *   post-rally caution = exhaustion at the top (distribution risk)
 *
 * For GOOGL 2026-05-18: position 95 %, +16 % over 6 weeks, 그레이브스톤도지
 * — clearly the latter. Falling into the 매복 branch sent the wrong
 * message ("기다리면 폭발할 자리") to a user holding GOOGL at +45 %.
 *
 * Triggers when:
 *   - position_in_52w ≥ 0.85 (near recent high)
 *   - rally_8w_pct ≥ 0.10  (meaningful recent gain)
 *   - the last candle has an upper-wick rejection signal
 *     (그레이브스톤도지 / 유성형 / 역망치형) OR a tight 4-bar box
 */
export function isPostRallyCaution(r: AnalysisResult): boolean {
  const pos = r.position_in_52w;
  const rally = r.rally_8w_pct;
  if (typeof pos !== "number" || pos < 0.85) return false;
  if (typeof rally !== "number" || rally < 0.10) return false;
  const tags = r.last_candle?.tags ?? [];
  const upperWickReversal =
    tags.includes("그레이브스톤도지")
    || tags.includes("유성형")
    || tags.includes("역망치형")
    || ((r.last_candle?.upper_wick_pct ?? 0) > 0.5);
  const tightBox =
    typeof r.consolidation_ratio === "number"
    && r.consolidation_ratio <= 0.06;
  return upperWickReversal || tightBox;
}

export function isAmbushSetup(r: AnalysisResult): boolean {
  // Disqualify when price is near 52-week high — that's post-rally
  // caution territory (different verdict above), not pre-breakout
  // accumulation. 매복's whole semantic is "supply still being
  // absorbed in the box"; a chart at 95 % of 52w is past that phase.
  const pos = r.position_in_52w;
  if (typeof pos === "number" && pos >= 0.85) return false;

  // Disqualify when price has already cleared 주봉 10MA meaningfully
  // (> +5 %). 매복 narrative is "포킹 트리거 위로 터질 때까지 매복" —
  // if last_close is already +5 % above the ma_10w trigger, the
  // trigger has effectively fired, not still pending. 088350.KS
  // 2026-05-20 reported case: last_close 5,300, ma_10w 4,944 (+7.2 %),
  // 매복 분기 fired with narrative "4,944원 위로 매복" → contradicts
  // the visible price. Threshold tuned to +5 %: 국보디자인 case
  // (+4.2 % over ma_10w with tight box + drying volume + indecision
  // candle) still classifies as 매복 (book: 자리만 약간 벗어난 box
  // 상태), while 088350.KS-style clear breakouts route to BUY proper.
  const ma10w = r.trend.weekly?.ma_10;
  if (typeof ma10w === "number" && ma10w > 0 && r.last_close > ma10w * 1.05) {
    return false;
  }

  const hasSetupPattern = (r.patterns ?? []).some(
    (p) => typeof p.kind === "string" && p.kind.includes("수렴 매복"),
  );
  // Volume "drying up" — case 12 explicitly, OR case 7 (bullish accumulation
  // complete) which the book also reads as "more sellers exhausted than
  // buyers exhausted = upcoming break". Case 8 (top + drop) is the
  // bearish-tilted variant we DON'T want to lump in.
  const vc = r.volume_case;
  const dryingVolume = vc?.case === 12 || vc?.case === 7;
  const lc = r.last_candle;
  const indecisionCandle =
    !!lc && (
      (lc.tags ?? []).some((t) =>
        ["도지", "눈썹캔들", "망치형", "교수형", "역망치형", "유성형",
         "드래곤플라이도지", "그레이브스톤도지"].includes(t),
      )
      || lc.body_pct < 0.2
    );
  // Tight recent box — 4-bar (max-min)/close ≤ 6 %. Computed in
  // analyzer; protects against the 국보디자인 case where the strict
  // MA-convergence detector misses because 60-week MA is too far.
  const tightBox =
    typeof r.consolidation_ratio === "number"
    && r.consolidation_ratio <= 0.06;
  // Need ≥2 of FOUR signals — setup pattern, drying volume, indecision
  // candle, tight box. Any single hit alone is too weak to flip a
  // STRONG_BUY into 매복.
  const hits = [hasSetupPattern, dryingVolume, indecisionCandle, tightBox]
    .filter(Boolean).length;
  return hits >= 2;
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

  // Multi-bar candle context tags (Phase 2 P2 — book p214/247-250).
  const lcTags = r.last_candle?.tags ?? [];
  if (lcTags.includes("구라캔들")) {
    out.push("구라캔들 — 큰 봉인데 거래량 부족 (책 p214): 가짜 신호 의심.");
  }
  if (lcTags.includes("양팔봉")) {
    out.push("양팔봉 — 위/아래 꼬리 모두 큼 (책 p247): 방향 미정, 다음 봉 관찰.");
  }
  if (lcTags.includes("은둔형장대양봉")) {
    out.push("은둔형 장대양봉 — 3봉 누적 +5 %+ (책 p249): 분할 매집 진행 중.");
  }
  if (lcTags.includes("주고받고")) {
    out.push("주고받고 캔들 — 장대양봉 후 안전지대 안 작은 음봉 (책 p250): 정상 소화.");
  }

  // Invalidated patterns surface as warnings on every verdict color
  // (including BUY/STRONG_BUY where they'd otherwise quietly inflate
  // the score) so users see the contradiction.
  for (const p of r.patterns ?? []) {
    if (p.invalidated && p.completed) {
      out.push(
        `${p.kind} 패턴 무효화 — ${p.invalidation_reason ?? "전저점/돌파선 재이탈"}.`,
      );
    }
    // 거래량 단조 룰 미충족 — book treats this as "페이크 캔들" risk.
    const fake = (p.extra as { fake_volume?: boolean } | undefined)?.fake_volume;
    if (fake && p.completed && !p.invalidated) {
      out.push(
        `${p.kind} 거래량 룰 미충족 — 책 p254/p276: "페이크 캔들" 의심. confidence 자동 감소.`,
      );
    }
  }

  // Volume vs action dissonance. Skip case 12 "수렴기 거래량 감소" —
  // that's bullish (accumulation finishing), not a contradiction.
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

  // Price runaway above 240MA — entering chase zone
  if (bullishAction && r.trend.weekly?.ma_240) {
    const pct = (r.last_close / r.trend.weekly.ma_240 - 1) * 100;
    if (pct > 80) {
      out.push(`주봉 240MA 대비 +${pct.toFixed(0)}% — 신규 매수 영역 멀리 벗어남.`);
    }
  }

  // Price BELOW weekly 240MA — book's 죽은 차트 zone. Normally the
  // monthly 240MA gate catches this in the analyzer and forces AVOID
  // action, but when monthly history is short (5y is < 240 months),
  // the monthly check returns null and the bullish action slips
  // through with no explicit warning. Surface the dissonance.
  if (
    bullishAction
    && r.trend.weekly?.above_ma_240 === false
    && r.trend.weekly?.ma_240
  ) {
    const pct = (r.last_close / r.trend.weekly.ma_240 - 1) * 100;
    out.push(
      `주봉 240MA(${formatPrice(r.trend.weekly.ma_240, r.ticker)}) 아래 ${pct.toFixed(0)}% — ` +
      "책 기준 죽은 차트 영역. 월봉 240MA 부재로 직접 AVOID 안 가지만 신규 매수 신중.",
    );
  }

  return out;
}

function verdictCard(
  tone: "emerald" | "amber" | "rose" | "zinc",
  icon: string,
  title: string,
  lines: string[],
  warnings: string[] = [],
  headerChip: ReactNode = null,
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
        {headerChip}
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
