/**
 * Screener preset registry.
 *
 * 2026-05-25 site-direction reset: collapsed from 6 presets to 1
 * ("책 정신 매수 후보"). The 5 removed presets (가치투자 클래식 /
 * 딥밸류 / 퀄리티 성장주 / 고배당 안전 / 마법공식) were value-investing
 * philosophies that don't sit cleanly with the book's trend-following
 * stance — keeping them alongside the book preset forced users to
 * mentally pick between contradictory signal sets each visit.
 *
 * The PRESETS array is kept (even at length 1) so future presets that
 * DO align with the book spirit can slot in without restructuring
 * the page. See feedback_site_direction.md for the criteria.
 *
 * Filter type fields kept narrow — only what the single preset uses.
 * The screener_results RPC still accepts the old fundamental-filter
 * parameters; we just pass null for them so the SQL WHERE collapses
 * to (actionIn + bookScoreMin + roeMin + sub-filters).
 */

export type ScreenerFilter = {
  // 분석 신호 — actionIn 은 ANY 매치 (STRONG_BUY OR BUY 처럼 여러개 가능).
  actionIn?: Array<"STRONG_BUY" | "BUY" | "HOLD" | "AVOID" | "SELL" | "SELL_OR_SHORT">;
  bookScoreMin?: number;
  // 최소 ROE — 적자 회사 자동 제외 (책: 추세 + 펀더 양쪽). 0 이상 권장.
  roeMin?: number;
};

export interface ScreenerPreset {
  slug: string;
  emoji: string;
  title: string;
  /** "이 검색이 어떤 종목 찾는지" 한 줄 평. */
  oneLiner: string;
  /** "이런 종목 발견 시 어떻게 행동할지" 액션 가이드. */
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
    // STRONG_BUY 도 포함해야 "책 정신 매수 후보" preset 답게 둘 다 보임.
    // action: "BUY" 단일 값으로 두면 강매수 종목이 자동 제외되는 버그
    // (사용자 보고 2026-05-20).
    filter: { actionIn: ["STRONG_BUY", "BUY"], bookScoreMin: 0.7, roeMin: 0.05 },
  },
];

export const DEFAULT_PRESET_SLUG = PRESETS[0].slug;

export function findPreset(slug: string | undefined): ScreenerPreset | null {
  if (!slug) return null;
  return PRESETS.find((p) => p.slug === slug) ?? null;
}
