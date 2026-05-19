/**
 * Rich interpretations for market-signal data — market warnings, short
 * sales, dividends. Style follows the user's stated tone:
 *
 *   1. Concrete numbers ("공매도 잔고 4.2%, 시장 평균 1.5%의 ~3배")
 *   2. Scenarios ("이렇게 되면 / 저렇게 되면")
 *   3. Action ("그 전에 이렇게 해라")
 *
 * Each interpreter returns a small structured object the UI renders into
 * a color-coded card. Pure functions — vitest-friendly, no React or
 * Supabase. Schema-stable inputs come from the new tables created in
 * migration 027.
 */

export type Tone = "good" | "neutral" | "warn" | "bad";

export interface SignalCard {
  tone: Tone;
  /** Headline tag (e.g. "🟢 정상", "🔴 거래정지"). */
  label: string;
  /** One-line state. */
  oneLiner: string;
  /** Numbered/labeled scenario lines — typically 2 (A / B). */
  scenarios?: { tag: string; body: string }[];
  /** Action prescriptions. */
  actions: string[];
}

const TONE_LABEL: Record<Tone, string> = {
  good: "🟢 정상",
  neutral: "🟡 주의",
  warn: "🟠 경고",
  bad: "🔴 위험",
};

// ─────────────────────────────────────────────────────────────────────
// Market warnings (KRX 시장조치)
// ─────────────────────────────────────────────────────────────────────

export type WarningLevel =
  | "trading_halt"
  | "surveillance"
  | "risk"
  | "warning"
  | "caution"
  | "overheat";

export interface MarketWarning {
  level: WarningLevel;
  reason: string | null;
  designated_at: string | null;
  expires_at: string | null;
}

/**
 * Interpret a stock's active market warnings. Returns null when there
 * are none — caller hides the section in that case (no point
 * cluttering a clean stock with a "정상" badge).
 */
export function interpretMarketWarnings(
  warnings: MarketWarning[],
): SignalCard | null {
  if (!warnings || warnings.length === 0) return null;
  // Sort by severity — most critical first determines the card tone.
  const order: Record<WarningLevel, number> = {
    trading_halt: 0,
    surveillance: 1,
    risk: 2,
    warning: 3,
    caution: 4,
    overheat: 5,
  };
  const sorted = [...warnings].sort((a, b) => order[a.level] - order[b.level]);
  const worst = sorted[0];

  const dateSuffix = formatDateRange(worst.designated_at, worst.expires_at);

  if (worst.level === "trading_halt") {
    return {
      tone: "bad",
      label: "🔴 거래정지",
      oneLiner:
        `매매 자체가 막힌 상태${dateSuffix}. ` +
        (worst.reason ? `사유: ${worst.reason}. ` : "") +
        "해제일까지 매수·매도 불가.",
      actions: [
        worst.expires_at
          ? `보유 중: 해제 예정 ${worst.expires_at} 까지 대기. 해제 후 첫 1-3 영업일은 변동성 폭증, 분할 청산 권장.`
          : "보유 중: 해제 공시 대기 (KRX 공시 알림). 해제 후 첫 1-3 영업일은 변동성 폭증, 분할 청산 권장.",
        "관심 종목: 해제 + 사유 해소 (예: 회계감리 종료) 후에만 신규 검토.",
      ],
    };
  }

  if (worst.level === "surveillance") {
    return {
      tone: "bad",
      label: "🔴 관리종목",
      oneLiner:
        `KRX가 상장폐지 가능성 모니터링 중${dateSuffix}. ` +
        (worst.reason ? `사유: ${worst.reason}. ` : "") +
        "사유 해소 안 되면 거래정지 / 상폐 수순.",
      scenarios: [
        {
          tag: "✅ 회복 시나리오",
          body: "다음 사업보고서 (대개 결산기 + 90일) 에서 자본잠식 / 매출 미달 사유 해소 → 관리종목 해제, 주가 단기 반등 가능.",
        },
        {
          tag: "⚠️ 악화 시나리오",
          body: "사유 미해소 → 거래정지 → 상장폐지 결정 → 정리매매 시 90%+ 하락 예시 다수.",
        },
      ],
      actions: [
        "신규 매수 X — 책 정신상 자본 보전 1순위.",
        "보유 중: 분기 사업보고서 일정 (D-30) 전에 청산 검토. 도박 보유는 책 원칙 위반.",
      ],
    };
  }

  if (worst.level === "risk") {
    return {
      tone: "bad",
      label: "🔴 투자위험",
      oneLiner:
        `단기 과열이 지속되어 KRX가 매수 자제 권고${dateSuffix}. ` +
        "다음 단계는 거래정지 가능.",
      scenarios: [
        {
          tag: "📉 조정 시나리오",
          body: "단기 -20-30% 급락 가능 — 과열 종목의 평균 패턴.",
        },
        {
          tag: "🚨 거래정지 시나리오",
          body: "위험 미해소 시 3일 거래정지로 escalate. 정지 해제 후 추가 하락 가능.",
        },
      ],
      actions: [
        worst.expires_at
          ? `보유자: ${worst.expires_at} 만료 전 1/2 ~ 2/3 익절 권장. 남은 비중은 trailing stop.`
          : "보유자: 1/2 ~ 2/3 익절 권장. 남은 비중은 trailing stop.",
        "관심자: 신규 매수 보류. 위험 해제 + 단기 조정 (-20%↓) 후 재검토.",
      ],
    };
  }

  if (worst.level === "warning") {
    return {
      tone: "warn",
      label: "🟠 투자경고",
      oneLiner:
        `단기 50%+ 급등으로 분류${dateSuffix}. ` +
        "다음 단계 = 투자위험, 그 다음 = 거래정지.",
      actions: [
        "보유자: 일부 익절 시작 (보유 수량의 1/3 ~ 1/2). 그 후 남은 비중은 손절가를 현재가 -5%로 올려두고 추세 끊기면 자동 청산.",
        worst.expires_at
          ? `신규 매수는 보류 — ${worst.expires_at} 경고 만료 후 차분히 차트 다시 보기.`
          : "신규 매수는 보류 — 너무 단기 급등한 종목은 보통 30-50% 조정 후 안정화.",
      ],
    };
  }

  if (worst.level === "caution") {
    return {
      tone: "warn",
      label: "🟠 투자주의",
      oneLiner: `1단계 경고${dateSuffix}. KRX가 거래 모니터링 강화 중.`,
      actions: [
        "추가 매수 자제. 모니터링 단계는 빠르게 escalate 될 수 있음.",
        "보유 중이면 stop-loss 미리 설정.",
      ],
    };
  }

  // overheat
  return {
    tone: "neutral",
    label: "🟡 단기과열",
    oneLiner:
      `지수 대비 단기 급등${dateSuffix} — 변동성 ↑↑. 3일간 매매 정지 가능성.`,
    actions: [
      "단기 트레이딩 자제 — 변동성에 휘둘려 손실 확률 ↑.",
      "보유자는 trailing stop, 미보유는 과열 해제 대기.",
    ],
  };
}

function formatDateRange(
  designated: string | null,
  expires: string | null,
): string {
  if (designated && expires) return ` (${designated} ~ ${expires})`;
  if (designated) return ` (${designated} 지정)`;
  if (expires) return ` (~${expires} 예정)`;
  return "";
}

// ─────────────────────────────────────────────────────────────────────
// Short sales (공매도)
// ─────────────────────────────────────────────────────────────────────

export interface ShortSalesSummary {
  /** Most recent day with data (YYYY-MM-DD). */
  latestDay: string | null;
  /** balance_shares / outstanding shares — typical KOSPI mean ~1.5%. */
  balanceRatio: number | null;
  /** today's short volume / today's total volume — daily intensity. */
  todayRatio: number | null;
  /** 5-day rolling average of `todayRatio` to spot a trend shift. */
  fiveDayAvgRatio: number | null;
}

export function interpretShortSales(s: ShortSalesSummary): SignalCard | null {
  if (s.balanceRatio == null && s.todayRatio == null) return null;

  // Balance ratio is the structural signal. KOSPI universe averages
  // ~1.5%; >3% counts as elevated, >5% as crowded.
  const bal = s.balanceRatio ?? 0;
  const today = s.todayRatio ?? 0;

  const balPct = (bal * 100).toFixed(2);
  const todayPct = (today * 100).toFixed(1);
  const trendUp =
    s.fiveDayAvgRatio != null &&
    s.todayRatio != null &&
    s.todayRatio > s.fiveDayAvgRatio * 1.5;

  const asOf = s.latestDay ? ` (기준일 ${s.latestDay})` : "";

  if (bal >= 0.05) {
    return {
      tone: "warn",
      label: "🟠 공매도 잔고 과대",
      oneLiner:
        `공매도 잔고 ${balPct}%${asOf} — 코스피 평균(약 1.5%)의 3배 이상. ` +
        "이 주가가 떨어질 거라고 베팅한 물량이 시장 평균보다 훨씬 많다는 뜻.",
      scenarios: [
        {
          tag: "📉 추가 하락 시나리오",
          body:
            "공매도 측이 맞다고 판단되면 베팅이 더 쌓임 → 매도 압력 지속. " +
            "특별한 호재가 없으면 하락 추세 계속될 가능성.",
        },
        {
          tag: "📈 급반등 시나리오 (숏커버링)",
          body:
            `큰 호재 (실적 깜짝 발표, 인수합병 등) + 거래량 폭증이 동반되면, ` +
            `공매도자들이 손해를 줄이려고 일제히 매수 (= 공매도 청산) → 주가 급등. ` +
            `잔고 ${balPct}% 정도면 이런 급반등 잠재력이 큰 편.`,
        },
      ],
      actions: [
        "보유 중: 현재가 -5% 정도에 손절가 설정해두기 (수익이 늘면 손절가도 같이 올리기). 공매도가 누적된 종목은 위험 신호.",
        "매수 검토 중: 큰 호재 + 거래량 평소의 2배 이상이 동시에 터질 때만 진입. " +
          "차트가 정렬 (단기/중기/장기 이동평균선이 위에서 아래로 정렬) 됐을 때만.",
      ],
    };
  }

  if (bal >= 0.03) {
    return {
      tone: "neutral",
      label: "🟡 공매도 잔고 다소 높음",
      oneLiner:
        `공매도 잔고 ${balPct}%, 오늘 비중 ${todayPct}%${asOf}. ` +
        (trendUp ? "최근 5일 평균보다 빠르게 증가 중 — 약세 베팅 가속. " : "") +
        "시장 평균(1.5%)보단 높지만 위험 수준은 아직 X.",
      actions: [
        "추가 매수할 거면 분할 진입 (한 번에 다 사지 말고 2-3번 나눠서).",
        "공매도 잔고 추이 주시 — 5%↑로 올라가면 위험 단계로 격상.",
      ],
    };
  }

  if (today >= 0.30) {
    return {
      tone: "neutral",
      label: "🟡 오늘 공매도 집중",
      oneLiner:
        `오늘 거래량의 ${todayPct}%가 공매도${asOf}. ` +
        "전체 잔고는 평이하지만 단기 매도 압력이 강함.",
      actions: [
        "단기 매수 보류 — 오늘처럼 공매도 집중되는 날 패턴이 끊긴 뒤 진입.",
        "보유 중이면 다음날 갭하락 가능성 염두에 손절가 점검.",
      ],
    };
  }

  return {
    tone: "good",
    label: "🟢 공매도 평이",
    oneLiner:
      `공매도 잔고 ${balPct}%, 오늘 비중 ${todayPct}%${asOf}. ` +
      "시장 평균 수준 — 공매도 측면에선 부담 없음.",
    actions: ["공매도는 매매 결정에 영향 X. 추세 / 패턴 / 거래량 신호 우선."],
  };
}

// ─────────────────────────────────────────────────────────────────────
// Dividends (배당)
// ─────────────────────────────────────────────────────────────────────

export interface DividendInfo {
  exDividend: string | null;        // YYYY-MM-DD, 배당락일
  recordDate: string | null;
  paymentDate: string | null;
  dps: number | null;                // 주당 배당금 (KRW)
  yieldPct: number | null;           // 배당수익률 (%)
  todayIso: string;                  // for D-N calculation in the caller
}

export function interpretDividend(d: DividendInfo): SignalCard | null {
  if (!d.exDividend && d.yieldPct == null) return null;

  // Days until ex-dividend; negative if already past.
  let daysUntil: number | null = null;
  if (d.exDividend) {
    const t = (new Date(d.exDividend).getTime() - new Date(d.todayIso).getTime()) /
      86_400_000;
    daysUntil = Math.round(t);
  }

  const yieldStr = d.yieldPct != null ? `${d.yieldPct.toFixed(2)}%` : "—";
  const dpsStr = d.dps != null ? `${Math.round(d.dps).toLocaleString("ko-KR")}원` : "—";

  // Already past — show "next batting" framing.
  if (daysUntil != null && daysUntil < 0) {
    return {
      tone: "neutral",
      label: "📆 배당락 종료",
      oneLiner:
        `직전 배당락 ${d.exDividend} (${Math.abs(daysUntil)}일 전), DPS ${dpsStr}, 수익률 ${yieldStr}. ` +
        "다음 배당락은 일반적으로 결산기 직전 (12월말 / 3월말).",
      actions: [
        "지금 매수해도 직전 배당은 못 받음. 배당 목적이면 다음 일정 (대개 12월) 까지 다른 종목 모색.",
        "매매 결정엔 영향 X — 차트 신호로 판단.",
      ],
    };
  }

  // 0 ≤ daysUntil ≤ 7: imminent.
  if (daysUntil != null && daysUntil >= 0 && daysUntil <= 7) {
    const lastBuyDay =
      daysUntil > 0
        ? `${addDays(d.exDividend!, -1)} (D-${daysUntil})`
        : "오늘이 배당락 당일";
    return {
      tone: "warn",
      label: "📆 배당락 임박",
      oneLiner:
        `배당락일 ${d.exDividend} — 매수해서 배당 받으려면 ${lastBuyDay} 까지 매수해야 함. ` +
        `주당 배당금 ${dpsStr} / 배당수익률 ${yieldStr}.`,
      scenarios: [
        {
          tag: "📉 배당락 당일 (D-day)",
          body:
            `시초가에서 약 -${yieldStr} 정도 자동 하락 예상. ` +
            "이건 약세 신호가 아니라 회계상 효과 — 배당 받을 권리가 가격에서 빠지는 거.",
        },
        {
          tag: "💸 배당 받고 팔까 그냥 팔까?",
          body:
            `배당 받으면 배당세 15.4% 떼임. ${yieldStr} 받고 ${yieldStr} 떨어진 가격에 팔면, 세금 때문에 결과적으로 손해일 수 있음. ` +
            `한국 개인 투자자는 주식 양도세 없으니 (대주주 제외), 단순 비교 시 배당 받지 않는 게 유리한 경우도.`,
        },
      ],
      actions: [
        `장기 보유 의도면: 그냥 보유. ${yieldStr} 받고 일시 하락은 시간이 지나면 회복.`,
        "단기 트레이더면: 배당락 전날 매도 / 다음날 재매수가 세후 유리한 경우 많음. " +
          "단, 다음날 갭하락 시점 못 잡으면 손해 — 차트 신호 우선.",
      ],
    };
  }

  // High yield, no imminent date — passive carrot.
  if (d.yieldPct != null && d.yieldPct >= 4) {
    return {
      tone: "good",
      label: "🟢 고배당주",
      oneLiner:
        `배당수익률 ${yieldStr} — KOSPI 평균 (~2%) 의 2배 이상. ` +
        (d.exDividend ? `다음 배당락 ${d.exDividend}.` : ""),
      actions: [
        "장기 보유 시 연 " + yieldStr + " 가까이 자동 수익. 차트 매수 자리 + 고배당 = 좋은 조합.",
        d.exDividend
          ? `배당락 D-30 부터는 매수세 강해지는 패턴 — 차트 정배열이면 적극 매수 검토.`
          : "다음 배당 일정 공시 확인.",
      ],
    };
  }

  return {
    tone: "neutral",
    label: "📆 배당 정보",
    oneLiner:
      `배당수익률 ${yieldStr}` +
      (d.exDividend ? `, 다음 배당락 ${d.exDividend} (D-${daysUntil}).` : "."),
    actions: ["배당이 매매 결정에 큰 영향은 아님. 추세 / 패턴 우선."],
  };
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + n);
  return dt.toISOString().slice(0, 10);
}

// ─────────────────────────────────────────────────────────────────────
// Calendar / seasonal (Halloween + Korean events)
// ─────────────────────────────────────────────────────────────────────

export type SeasonalRegime = "bullish_window" | "bearish_window";

export interface SeasonalContext {
  /** Today as YYYY-MM-DD (so this is testable with frozen time). */
  todayIso: string;
}

/**
 * The Halloween indicator + Korean-market overlay. Returns the current
 * regime + a card the dashboard renders. May-Oct historically averages
 * ~3% return; Nov-Apr ~8%+ in US, Korea milder but same direction.
 */
export function interpretSeasonal(ctx: SeasonalContext): SignalCard {
  const month = Number(ctx.todayIso.slice(5, 7));
  const day = Number(ctx.todayIso.slice(8, 10));
  const inBullishWindow = month <= 4 || month >= 11;

  // Upcoming Korean-market dates worth flagging.
  const upcoming: string[] = [];
  // Year-end dividend record (대개 12월 마지막 영업일 전).
  if (month === 12 && day < 28) {
    upcoming.push("📅 12월 말: 연말 배당 기준일 — 고배당주 가장 강한 시즌 (단, 배당락일 ~-2% 명심).");
  }
  // Spring shareholder meeting season.
  if (month === 3) {
    upcoming.push("📅 3월: 정기주총 시즌 — 자사주 매입 / 배당 정책 변경 공시 다수.");
  }
  // MSCI rebal.
  if ([2, 5, 8, 11].includes(month)) {
    upcoming.push("📅 MSCI 분기 리밸런싱 발표 시즌 (15일경) — 편입/편출 종목 단기 ±5-10%.");
  }

  const year = Number(ctx.todayIso.slice(0, 4));
  const nextTransition = inBullishWindow
    ? `${month >= 11 ? year + 1 : year}-05-01`  // bullish window ends 5월 1일
    : `${year}-11-01`;                            // bearish window ends 11월 1일

  if (inBullishWindow) {
    return {
      tone: "good",
      label: "🟢 강세 시즌 (11월~4월)",
      oneLiner:
        `매년 11월~4월은 통계적으로 가장 강한 6개월 (\"Halloween effect\"). ` +
        `미국 시장 ~150년 평균 수익률 8%+, 한국은 3-4%. 구조적으로 매수 우호. ` +
        `이 시즌은 ${nextTransition} 까지.`,
      scenarios: [
        {
          tag: "📊 통계 근거",
          body:
            "11월-4월 vs 5월-10월 평균 수익률: 미국 S&P 500 +7.5% vs +0.4% (1950-2024 자료). " +
            "코스피 동일 기간 +4% vs +1%. 한국이 더 약하지만 같은 방향성.",
        },
      ],
      actions: [
        "이 기간에는 차트 매수 자리에서 적극 진입 OK. 자금 50-80% 사용 가능.",
        `${nextTransition} (5월 시작) 시점에 자동 보수 모드로 전환 — 익절 + 비중 축소.`,
        ...upcoming,
      ],
    };
  }

  return {
    tone: "neutral",
    label: "🟡 약세 시즌 (5월~10월)",
    oneLiner:
      `매년 5월~10월은 통계적으로 가장 약한 6개월. ` +
      `차트 매수 신호가 있어도 보수적 비중 (30-50%) 권장. ` +
      `이 시즌은 ${nextTransition} 까지.`,
    scenarios: [
      {
        tag: "📊 통계 근거",
        body:
          "5월-10월 평균 수익률은 11월-4월의 약 1/10. 큰 조정도 이 기간에 자주 발생 " +
          "(블랙 먼데이 1987-10, 리먼 사태 2008-09, 코로나 충격 2020-03 등).",
      },
    ],
    actions: [
      "신규 매수는 큰 호재 + 차트 정렬 (단기/중기/장기 평균선이 위→아래 순서) 동반될 때만. 분할 진입 필수.",
      `5월부터 점진 익절 → 10월 비중 최저 → ${nextTransition} (11월 시작) 부터 다시 적극.`,
      ...upcoming,
    ],
  };
}
