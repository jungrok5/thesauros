/**
 * Pure interpreters that turn financials_eval / factors_eval rows into
 * a structured "what does this mean + what should I do" verdict the
 * stock detail tabs render above the raw tables.
 *
 * The book ("캔들차트 추세추종") treats financials as a corroboration
 * layer, not the primary signal — even excellent fundamentals don't
 * justify a buy without trend + pattern alignment. The interpreters
 * keep that framing: takeaways reference "직접 매수 자격" (qualifier)
 * rather than standalone trading calls.
 *
 * Stays in /lib so vitest can exercise the rule branches without
 * hauling in React or supabase mocks.
 */
import type { FinancialsEvalRow, FactorsEvalRow } from "@/lib/supabase";

export type Tone = "good" | "neutral" | "warn" | "bad";

export interface Interpretation {
  /** Single-glance grade for the section header. */
  tone: Tone;
  /** Short label paired with `tone` ("🟢 우수" etc.). */
  label: string;
  /** One-line summary of overall state. */
  oneLiner: string;
  /** 2-4 actionable takeaways — each starts with the relevant context. */
  takeaways: string[];
}

const TONE_LABEL: Record<Tone, string> = {
  good: "🟢 우수",
  neutral: "🟡 양호",
  warn: "🟠 주의",
  bad: "🔴 위험",
};

function toneLabel(tone: Tone): string {
  return TONE_LABEL[tone];
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/**
 * Financials interpreter — focuses on profitability + safety + growth
 * trend, the three dimensions the book says actually matter for
 * "this company can survive its own setbacks."
 */
export function interpretFinancials(fin: FinancialsEvalRow): Interpretation {
  const roe = fin.roe;
  const opMargin = fin.op_margin;
  const debt = fin.debt_ratio;
  const revGrowth = fin.revenue_growth_yoy;

  // Score each dimension as -1 (bad), 0 (neutral), +1 (good).
  // The overall tone reflects the worst dimension, weighted slightly
  // toward safety (debt) — the book's "자본 보전 1순위".
  const profitTone = roe == null
    ? 0
    : roe >= 0.15
      ? 1
      : roe >= 0.08
        ? 0
        : -1;
  const safetyTone = debt == null
    ? 0
    : debt < 0.5
      ? 1
      : debt < 1.0
        ? 0
        : -1;
  const growthTone = revGrowth == null
    ? 0
    : revGrowth >= 0.10
      ? 1
      : revGrowth >= 0
        ? 0
        : -1;

  // Weighted aggregate: safety counts double — a profitable but
  // over-levered company is still a no-go in the book's lens.
  const aggregate = profitTone + 2 * safetyTone + growthTone;
  let tone: Tone;
  if (aggregate >= 3) tone = "good";
  else if (aggregate >= 1) tone = "neutral";
  else if (aggregate >= -1) tone = "warn";
  else tone = "bad";

  const oneLiner = buildFinancialsOneLiner({
    roe,
    opMargin,
    debt,
    revGrowth,
    tone,
  });

  const takeaways: string[] = [];

  if (revGrowth != null) {
    if (revGrowth >= 0.20) {
      takeaways.push(
        `매출 ${fmtPct(revGrowth)} 고성장 — 추세 동력 + 시장 점유율 확대 신호. 차트가 정배열이면 매수 자격 ↑.`,
      );
    } else if (revGrowth >= 0.10) {
      takeaways.push(
        `매출 ${fmtPct(revGrowth)} 안정 성장. 펀더멘털은 trend-follower 의 안전판 — 패턴 신호와 충돌 시 추세 우선.`,
      );
    } else if (revGrowth >= 0) {
      takeaways.push(
        `매출 +${fmtPct(revGrowth)} (저성장). 직접 매수보단 자리만 관망 — 책 정신상 둔화 사이클은 추세 fade 위험.`,
      );
    } else {
      takeaways.push(
        `매출 ${fmtPct(revGrowth)} (역성장). 사업 축소 사이클 — 반등 패턴 (쌍바닥, 컵핸들) 이 차트로 확인되기 전엔 회피.`,
      );
    }
  }

  if (roe != null && opMargin != null) {
    if (roe >= 0.15 && opMargin >= 0.10) {
      takeaways.push(
        `ROE ${fmtPct(roe)} + 영업이익률 ${fmtPct(opMargin)} → 수익성 우수. 매수 자리에서 buy-and-hold 후보.`,
      );
    } else if (roe < 0 || opMargin < 0) {
      takeaways.push(
        `ROE ${fmtPct(roe)} · 영업이익률 ${fmtPct(opMargin)} — 적자 상태. 책 정신상 매수 후보 X (recovery 베팅은 별도).`,
      );
    } else {
      takeaways.push(
        `ROE ${fmtPct(roe)} · 영업이익률 ${fmtPct(opMargin)} — 평이한 수익성. 추세 + 거래량 신호가 강해야 매수.`,
      );
    }
  }

  if (debt != null) {
    if (debt < 0.5) {
      takeaways.push(
        `부채비율 ${fmtPct(debt, 0)} — 매우 안전. 시장 충격에 버틸 체력 OK.`,
      );
    } else if (debt < 1.0) {
      takeaways.push(
        `부채비율 ${fmtPct(debt, 0)} — 평이. 이자비용 민감 (금리 인상 사이클에 영업이익 압축 위험).`,
      );
    } else {
      takeaways.push(
        `부채비율 ${fmtPct(debt, 0)} — 과도. 책 §자본 보전 관점에서 위험 — 직접 매수 회피, 추세 강할 때만 작은 비중.`,
      );
    }
  }

  return { tone, label: toneLabel(tone), oneLiner, takeaways };
}

function buildFinancialsOneLiner(args: {
  roe: number | null;
  opMargin: number | null;
  debt: number | null;
  revGrowth: number | null;
  tone: Tone;
}): string {
  const parts: string[] = [];
  if (args.revGrowth != null) {
    if (args.revGrowth >= 0.10) parts.push("성장 견조");
    else if (args.revGrowth >= 0) parts.push("성장 둔화");
    else parts.push("역성장");
  }
  if (args.roe != null) {
    if (args.roe >= 0.15) parts.push("수익성 우수");
    else if (args.roe >= 0.08) parts.push("수익성 보통");
    else if (args.roe >= 0) parts.push("수익성 약함");
    else parts.push("적자");
  }
  if (args.debt != null) {
    if (args.debt < 0.5) parts.push("재무 안전");
    else if (args.debt < 1.0) parts.push("부채 평이");
    else parts.push("부채 과도");
  }
  if (parts.length === 0) return "지표 부족 — 추세 신호로만 판단";

  const suffix =
    args.tone === "good"
      ? " → 추세 + 패턴이 좋으면 매수 후보."
      : args.tone === "neutral"
        ? " → 차트 신호 우선, 펀더는 보조."
        : args.tone === "warn"
          ? " → 보수적 접근, 강한 추세만 추격."
          : " → 직접 매수 회피, 관망 권장.";

  return parts.join(" · ") + suffix;
}

// ---------------------------------------------------------------------
// Factors interpreter
// ---------------------------------------------------------------------

/**
 * Factors interpreter — adds the valuation dimension on top of the
 * financials view. The 4 gates (강환국·그레이엄·마법공식·버핏) are
 * the "celebrity screens"; we surface a count + the dominant theme.
 */
export function interpretFactors(fac: FactorsEvalRow): Interpretation {
  const per = fac.per;
  const pbr = fac.pbr;
  const value = fac.value_score ?? 0;
  const growth = fac.growth_score ?? 0;
  const safety = fac.safety_score ?? 0;
  const quality = fac.quality_score ?? 0;
  const total = value + growth + safety + quality;

  const gatesPassed = [
    fac.passes_kang_value,
    fac.passes_graham,
    fac.passes_magic_formula,
    fac.passes_buffett,
  ].filter((v) => v === true).length;
  const gatesEvaluable = [
    fac.passes_kang_value,
    fac.passes_graham,
    fac.passes_magic_formula,
    fac.passes_buffett,
  ].filter((v) => v != null).length;

  let tone: Tone;
  if (gatesPassed >= 3 || total >= 32) tone = "good";
  else if (gatesPassed >= 1 || total >= 22) tone = "neutral";
  else if (total >= 12) tone = "warn";
  else tone = "bad";

  const valueText =
    per != null && per > 0
      ? `PER ${per.toFixed(1)}` + (pbr != null ? ` · PBR ${pbr.toFixed(2)}` : "")
      : "PER/PBR 미산정 (시가총액 데이터 부족)";

  const oneLiner =
    `${valueText} · 가치 ${value}/10 · 성장 ${growth}/10 · 안전 ${safety}/10 · 수익 ${quality}/10` +
    (gatesEvaluable > 0
      ? ` → 4대 스크리닝 ${gatesPassed}/${gatesEvaluable} 통과`
      : "");

  const takeaways: string[] = [];

  if (per != null && per > 0) {
    if (per < 10) {
      takeaways.push(
        `PER ${per.toFixed(1)} — 시장 평균 이하 (저평가권). 가치 투자자에게 매력, 단 책은 가치만으로 매수 X.`,
      );
    } else if (per < 20) {
      takeaways.push(
        `PER ${per.toFixed(1)} — 시장 평균권. 성장률이 받쳐주면 적정, 둔화 중이면 비싼 편.`,
      );
    } else {
      takeaways.push(
        `PER ${per.toFixed(1)} — 고평가권. 매출 +20%/년 이상 고성장이 동반될 때만 정당화 가능.`,
      );
    }
  } else {
    takeaways.push(
      `PER 미산정 — KR 종목은 pykrx, US 는 SEC shares outstanding 필요. 다음 주간 cron 후 자동 채워짐.`,
    );
  }

  if (gatesPassed >= 3) {
    takeaways.push(
      `4대 스크리닝 ${gatesPassed}/4 통과 — 가치+안전+수익이 동시에 충족된 드문 케이스. 차트 매수 자리만 만들어지면 강한 후보.`,
    );
  } else if (gatesPassed >= 1) {
    const which = [
      fac.passes_kang_value && "강환국",
      fac.passes_graham && "그레이엄",
      fac.passes_magic_formula && "마법공식",
      fac.passes_buffett && "버핏형",
    ].filter(Boolean).join(", ");
    takeaways.push(
      `${which} 통과 — 일부 가치투자 기준만 충족. 추세 신호 강도 확인 필수.`,
    );
  } else if (gatesEvaluable > 0) {
    takeaways.push(
      `4대 스크리닝 0/${gatesEvaluable} 통과 — 가치투자 관점은 비호의적. 단, 책의 추세추종 관점에선 무관.`,
    );
  }

  if (total >= 28) {
    takeaways.push(
      `4축 종합 ${total}/40 — 펀더 균형 우수. 매수 자리에서 비중 확대 가능.`,
    );
  } else if (total < 12) {
    takeaways.push(
      `4축 종합 ${total}/40 — 펀더 균형 약함. 차트 신호 매우 강해야 매수.`,
    );
  }

  return { tone, label: toneLabel(tone), oneLiner, takeaways };
}
