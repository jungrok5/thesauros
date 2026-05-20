/**
 * Korean stock tax calculators (2026 세법 기준).
 *
 * 두 가지 시나리오:
 *
 *   1. estimateCapitalGainsTax — 미국 주식 (또는 해외) 양도세
 *      = (총 매매차익 - 250만원 기본공제) × 22% (지방세 포함)
 *      한국 개별주는 대주주 아니면 양도세 0% — 단순화 위해 미국 케이스만.
 *
 *   2. yearEndOptimizer — 연말 절세 매도 시기 추천
 *      사용자의 \"올해 누적 미국 차익\" + \"평가손익\" 입력 → 다음 안내:
 *        a. 250만 공제 한도가 얼마나 남아있는지
 *        b. 손실 종목 청산해서 차익 상쇄 가능한 금액
 *        c. 12 월 셋째 주까지 매도하면 올해 양도세 정산에 포함됨
 *
 *   3. estimateIsaPensionTransferRefund — ISA 만기 → 연금저축 이전 시
 *      세액공제 추가 — 이전 금액의 10% (최대 300만원) 의 16.5% (또는 13.2%).
 *
 * 모두 pure function — vitest 가능.
 */

const DEDUCT_OVERSEAS_KRW = 2_500_000;  // 연 250 만원 기본 공제
const RATE_OVERSEAS = 0.22;             // 22% (지방세 포함)
const ISA_TRANSFER_CAP_KRW = 3_000_000; // 300 만원 한도
const ISA_TRANSFER_LIMIT_RATIO = 0.10;  // 이전 금액의 10%
const REFUND_RATE_HIGH = 0.165;         // 종합소득 5,500 만원 이하
const REFUND_RATE_LOW = 0.132;          // 5,500 만원 초과

export interface CapitalGainsResult {
  totalGain: number;
  taxableGain: number;
  tax: number;
  netGain: number;
  /** 한 줄 평. */
  oneLiner: string;
}

/**
 * 해외 (미국) 주식 양도세. 한국은 대주주 아니면 X 이므로 생략.
 * totalGainKrw = 올해 누적 양도차익 (KRW).
 */
export function estimateCapitalGainsTax(
  totalGainKrw: number,
): CapitalGainsResult {
  const taxable = Math.max(0, totalGainKrw - DEDUCT_OVERSEAS_KRW);
  const tax = taxable * RATE_OVERSEAS;
  const net = totalGainKrw - tax;
  let oneLiner: string;
  if (totalGainKrw <= 0) {
    oneLiner = "차익 없음 — 양도세 X.";
  } else if (totalGainKrw <= DEDUCT_OVERSEAS_KRW) {
    const remaining = DEDUCT_OVERSEAS_KRW - totalGainKrw;
    oneLiner =
      `250 만원 기본공제 안에 들어서 양도세 0 원. ` +
      `${remaining.toLocaleString("ko-KR")} 원 더 익절해도 무세금.`;
  } else {
    oneLiner =
      `${taxable.toLocaleString("ko-KR")} 원에 22% = ` +
      `${tax.toLocaleString("ko-KR")} 원 양도세. ` +
      `세후 ${net.toLocaleString("ko-KR")} 원 손에.`;
  }
  return { totalGain: totalGainKrw, taxableGain: taxable, tax, netGain: net, oneLiner };
}

// ─────────────────────────────────────────────────────────────────────

export interface YearEndOptimizerInput {
  /** 올해 누적 해외 (미국 등) 양도차익 — 이미 매도해서 확정된 금액. */
  realizedYtdKrw: number;
  /** 보유 중 평가차익 (양수 = 익절시 더 세금, 음수 = 손실 종목). */
  unrealizedPnLKrw: number;
}

export interface YearEndOptimizerResult {
  /** 250 만 공제 남은 한도. */
  remainingDeductKrw: number;
  /** 추가 익절 시 면세 한도. */
  taxFreeBudgetKrw: number;
  /** 손실 청산으로 상쇄 가능한 차익 (음수면 N/A). */
  lossOffsetKrw: number;
  /** 추천 액션 리스트. */
  actions: string[];
}

/**
 * 연말 절세 매도 시기 — 12 월 셋째 주까지 매도하면 올해 양도세 정산
 * 포함. 사용자 입력 기반 시뮬레이션.
 */
export function yearEndOptimizer(
  input: YearEndOptimizerInput,
): YearEndOptimizerResult {
  const remaining = Math.max(0, DEDUCT_OVERSEAS_KRW - input.realizedYtdKrw);
  const lossOffset = input.unrealizedPnLKrw < 0
    ? Math.abs(input.unrealizedPnLKrw)
    : 0;
  // 면세 가능 = 250만 한도 남은 만큼 + 손실 청산 만큼.
  const taxFreeBudget = remaining + lossOffset;

  const actions: string[] = [];

  if (remaining > 0) {
    actions.push(
      `남은 250 만 공제 한도: ${remaining.toLocaleString("ko-KR")} 원. ` +
      `이만큼은 익절해도 양도세 0 원 — \"무세금 익절\" 영역이라 적극 활용.`,
    );
  } else {
    const overage = input.realizedYtdKrw - DEDUCT_OVERSEAS_KRW;
    actions.push(
      `이미 ${overage.toLocaleString("ko-KR")} 원 과세 구간 진입. ` +
      `추가 익절은 22% 양도세 발생 → 손실 청산으로 상쇄 검토.`,
    );
  }

  if (lossOffset > 0) {
    actions.push(
      `보유 중 평가손실 ${lossOffset.toLocaleString("ko-KR")} 원. ` +
      `이 종목 청산하면 같은 금액만큼 차익 상쇄 가능 — 한국엔 \"손익통산\" 룰. ` +
      `장기 신뢰 X 종목이면 손실 확정으로 절세, 회복 신뢰면 보유 유지.`,
    );
  }

  if (taxFreeBudget > 0 && input.unrealizedPnLKrw > 0) {
    actions.push(
      `평가차익 ${input.unrealizedPnLKrw.toLocaleString("ko-KR")} 원 중 ` +
      `${Math.min(taxFreeBudget, input.unrealizedPnLKrw).toLocaleString("ko-KR")} 원까지 ` +
      `면세로 익절 가능. 12 월 셋째 주 (대개 12/23 ~ 12/27) 까지 매도 결제일 포함되어야 ` +
      `올해 정산.`,
    );
  }

  actions.push(
    `다음 해 1 월에 ISA 새로 가입 — 매년 ISA 2,000 만 한도, 200 만 비과세 갱신.`,
  );

  return {
    remainingDeductKrw: remaining,
    taxFreeBudgetKrw: taxFreeBudget,
    lossOffsetKrw: lossOffset,
    actions,
  };
}

// ─────────────────────────────────────────────────────────────────────

export interface IsaTransferInput {
  /** ISA 만기 누적 평가금액 — 원금 + 이익. */
  isaBalanceKrw: number;
  /** 종합소득 5,500 만 원 초과 여부. */
  highIncome: boolean;
}

export interface IsaTransferResult {
  /** 연금저축으로 이전 가능한 금액 (실제 한도). */
  transferableKrw: number;
  /** 추가 세액공제 금액 (KRW). */
  extraRefundKrw: number;
  oneLiner: string;
}

export function estimateIsaPensionTransferRefund(
  input: IsaTransferInput,
): IsaTransferResult {
  // 이전 한도: ISA 잔액의 10% (최대 300 만).
  const transferable = Math.min(
    ISA_TRANSFER_CAP_KRW,
    Math.max(0, input.isaBalanceKrw * ISA_TRANSFER_LIMIT_RATIO),
  );
  const rate = input.highIncome ? REFUND_RATE_LOW : REFUND_RATE_HIGH;
  const extra = transferable * rate;
  return {
    transferableKrw: transferable,
    extraRefundKrw: extra,
    oneLiner:
      `ISA 만기 ${input.isaBalanceKrw.toLocaleString("ko-KR")} 원 → ` +
      `연금저축으로 ${transferable.toLocaleString("ko-KR")} 원 이전 → ` +
      `추가 세액공제 ${Math.round(extra).toLocaleString("ko-KR")} 원 (1 회성).`,
  };
}
