/**
 * Stock screener presets — named filter combos that map to a SQL WHERE
 * clause + a human-readable "이 검색의 의미" header for the result page.
 *
 * Tone — pure-Korean + plain words. Each preset includes:
 *   - title: short label for the card
 *   - oneLiner: what kind of stock this finds + why it's interesting
 *   - action: \"이런 종목들 발견하면 → 다음 단계는 X\" guidance
 *   - filter: a typed predicate the page uses to query Supabase
 *
 * No new schema — works off existing factors_eval + analyze_results.
 */

export type ScreenerFilter = {
  // Each field is optional; the page builds a WHERE that ANDs them all.
  perMax?: number;
  perMin?: number;
  pbrMax?: number;
  roeMin?: number;       // e.g. 0.10 for 10%
  debtRatioMax?: number; // e.g. 0.50 for 50%
  opMarginMin?: number;
  revenueGrowthMin?: number;
  // 책 정신 게이트
  passesBuffett?: boolean;
  passesGraham?: boolean;
  passesKangValue?: boolean;
  passesMagicFormula?: boolean;
  // 분석 신호
  action?: "STRONG_BUY" | "BUY" | "AVOID" | "SELL";
  bookScoreMin?: number;
};

export interface ScreenerPreset {
  slug: string;
  emoji: string;
  title: string;
  /** \"이 검색이 어떤 종목 찾는지\" 한 줄 평. */
  oneLiner: string;
  /** \"이런 종목 발견 시 어떻게 행동할지\" 액션 가이드. */
  action: string;
  filter: ScreenerFilter;
}

export const PRESETS: ScreenerPreset[] = [
  {
    slug: "book-buy",
    emoji: "📚",
    title: "책 정신 매수 후보",
    oneLiner:
      "차트 분석 + 펀더멘털 양쪽 통과 — 추세 정배열 + 240일 평균선 위 + " +
      "회사도 적자 X. 책에서 말하는 \"좋은 자리에 좋은 회사\" 케이스.",
    action:
      "후보 발견 시 책 정신대로: (1) 분할 매수 (한 번에 다 X), " +
      "(2) 매수 후 손절가 미리 설정, (3) 강세 시즌 (11~4월) 이면 적극, 약세 시즌 (5~10월) 이면 비중 절반.",
    filter: { action: "BUY", bookScoreMin: 0.7, roeMin: 0.05 },
  },
  {
    slug: "value-classic",
    emoji: "💎",
    title: "가치투자 클래식 (그레이엄 + 버핏 동시 통과)",
    oneLiner:
      "저평가 (PER < 15) + 재무 안정 (부채 < 50%) + 수익성 (ROE > 15%) " +
      "을 동시에 만족. 워런 버핏이 좋아할 만한 스타일.",
    action:
      "장기 보유에 적합. 단, 차트가 정배열 + 240MA 위 인지 따로 확인 " +
      "필요 — 가치주도 추세 깨지면 떨어지는 칼.",
    filter: { passesGraham: true, passesBuffett: true },
  },
  {
    slug: "value-deep",
    emoji: "🪙",
    title: "딥밸류 (저PER + 저PBR)",
    oneLiner:
      "PER 10 미만 + PBR 1 미만. 시장이 외면한 종목 — 회복 시 큰 수익 " +
      "가능하지만 \"가치 함정\" risk 도 있음 (계속 싸지기만 함).",
    action:
      "매수 전 회복 신호 확인 — 분기 실적 턴어라운드 / 자사주 매입 공시 / " +
      "외인 매수 전환 등. 신호 없으면 더 떨어질 가능성.",
    filter: { perMax: 10, pbrMax: 1.0, debtRatioMax: 1.0 },
  },
  {
    slug: "growth-quality",
    emoji: "🚀",
    title: "퀄리티 성장주",
    oneLiner:
      "매출 +10%↑ 성장 + ROE 15%↑ 수익성 + 부채 < 100% 안전. " +
      "거품 종목 (PBR > 5, PER > 40) 은 자동 제외 — 성장 + 가치 동시 합격.",
    action:
      "성장주는 약세 시즌 (5~10월) 에 -20~30% 조정 빈번. 분할 매수 + " +
      "조정 시 추매 전략. 주변 매크로 (금리 / VIX) 도 같이 모니터.",
    // PBR/PER 상한 추가 — "퀄리티 성장주" 인데 PBR 33배 에이피알 / SK하이닉스
    // PBR 10배 같은 거품주가 통과되던 문제 (2026-05-20). 성장 + 합리적
    // 가격 동시 합격 종목만 노출.
    filter: {
      revenueGrowthMin: 0.10,
      roeMin: 0.15,
      debtRatioMax: 1.0,
      pbrMax: 5,
      perMax: 40,
    },
  },
  {
    slug: "high-dividend-safe",
    emoji: "💰",
    title: "고배당 + 안전 (배당주)",
    oneLiner:
      "ROE 10%↑ + 부채 < 50% — 펀더 안전한 종목. " +
      "배당수익률은 종목 상세 페이지에서 따로 확인 (배당 정보 카드).",
    action:
      "배당락일 -2% 자동 하락 감안. 단기 매도 X → 장기 보유 → " +
      "배당 받고 시간이 가격 회복.",
    filter: { roeMin: 0.10, debtRatioMax: 0.50 },
  },
  {
    slug: "magic-formula",
    emoji: "🎩",
    title: "마법공식 (그린블랫)",
    oneLiner:
      "저PER (< 12) + 고영업이익률 (> 10%). 조엘 그린블랫의 \"좋은 회사 + " +
      "싼 가격\" 자동 발굴 공식.",
    action:
      "공식 자체는 백테스트에서 검증된 전략. 다만 책 정신상 차트 정배열 " +
      "동반 필수 — 가치 신호만 보고 들어가지 X.",
    filter: { passesMagicFormula: true },
  },
];

export function findPreset(slug: string | undefined): ScreenerPreset | null {
  if (!slug) return null;
  return PRESETS.find((p) => p.slug === slug) ?? null;
}
