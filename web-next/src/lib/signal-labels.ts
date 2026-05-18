/**
 * Map raw scan_results.signal_type to a human-readable Korean label
 * + direction so the UI doesn't dump `pattern_double_bottom` raw onto
 * the page (the user has no way to tell whether it's a buy or a sell).
 *
 * Bullish = 매수 신호 (가격이 올라간다는 신호)
 * Bearish = 매도 신호 (가격이 내려간다는 신호)
 */

export type SignalDirection = "bullish" | "bearish" | "neutral";

export interface SignalLabel {
  label: string;       // Korean short name
  direction: SignalDirection;
  /** Verbose Korean phrase for the "이유" column */
  phrase: string;
}

const PATTERN_LABELS: Record<string, SignalLabel> = {
  pattern_double_bottom: {
    label: "쌍바닥",
    direction: "bullish",
    phrase: "쌍바닥 (매수 반전 패턴)",
  },
  pattern_triple_bottom: {
    label: "삼중바닥",
    direction: "bullish",
    phrase: "삼중바닥 (매수 반전 패턴)",
  },
  pattern_inverse_head_and_shoulders: {
    label: "역H&S",
    direction: "bullish",
    phrase: "역헤드앤숄더 (매수 반전 패턴)",
  },
  pattern_forking: {
    label: "포킹",
    direction: "bullish",
    phrase: "포킹 — 상승 분기 (매수)",
  },
  pattern_cup_with_handle: {
    label: "컵핸들",
    direction: "bullish",
    phrase: "컵 위드 핸들 (매수 추세 지속)",
  },
  pattern_double_top: {
    label: "쌍천장",
    direction: "bearish",
    phrase: "쌍천장 (매도 반전 패턴)",
  },
  pattern_triple_top: {
    label: "삼중천장",
    direction: "bearish",
    phrase: "삼중천장 (매도 반전 패턴)",
  },
  pattern_head_and_shoulders: {
    label: "H&S",
    direction: "bearish",
    phrase: "헤드앤숄더 (매도 반전 패턴)",
  },
};

const VOLUME_LABELS: Record<string, SignalLabel> = {
  volume_case_3: {
    label: "거래량 폭증",
    direction: "bullish",
    phrase: "Case 3 — 바닥권 거래량 폭증 (매수 진입)",
  },
  volume_case_4: {
    label: "거래량 횡보",
    direction: "neutral",
    phrase: "Case 4 — 횡보권 거래량 폭증 (방향 대기)",
  },
  volume_case_7: {
    label: "역배 거래량",
    direction: "bearish",
    phrase: "Case 7 — 상승 중 거래량 급감 (매도 우려)",
  },
  volume_case_9: {
    label: "분배 거래량",
    direction: "bearish",
    phrase: "Case 9 — 분배 의심 거래량 (매도)",
  },
  volume_case_11: {
    label: "투매 거래량",
    direction: "bullish",
    phrase: "Case 11 — 투매 후 잔량 (바닥 신호)",
  },
};

const ACTION_LABELS: Record<string, SignalLabel> = {
  action_strong_buy: { label: "강한 매수", direction: "bullish",
    phrase: "다중 시간프레임 정렬 + 패턴 다중 발현 (강한 매수)" },
  action_buy: { label: "매수", direction: "bullish",
    phrase: "추세 우호 정렬 (매수)" },
  action_sell: { label: "매도", direction: "bearish",
    phrase: "10MA 이탈 (매도)" },
  action_sell_short: { label: "매도/인버스", direction: "bearish",
    phrase: "추세 사망 (청산 또는 인버스)" },
  action_avoid: { label: "회피", direction: "bearish",
    phrase: "240MA 아래 — 죽은 차트 (회피)" },
  action_hold: { label: "관망", direction: "neutral",
    phrase: "관망" },
};

export function labelFor(signalType: string): SignalLabel {
  return (
    PATTERN_LABELS[signalType] ??
    VOLUME_LABELS[signalType] ??
    ACTION_LABELS[signalType] ?? {
      label: signalType,
      direction: "neutral",
      phrase: signalType,
    }
  );
}

export function isBullishPattern(signalType: string): boolean {
  return PATTERN_LABELS[signalType]?.direction === "bullish";
}

export function isBearishPattern(signalType: string): boolean {
  return PATTERN_LABELS[signalType]?.direction === "bearish";
}

export const BULLISH_PATTERN_KEYS: string[] = Object.entries(PATTERN_LABELS)
  .filter(([, v]) => v.direction === "bullish")
  .map(([k]) => k);

export const BEARISH_PATTERN_KEYS: string[] = Object.entries(PATTERN_LABELS)
  .filter(([, v]) => v.direction === "bearish")
  .map(([k]) => k);

/** Tailwind color tokens for direction. */
export function directionStyle(d: SignalDirection): {
  bg: string; text: string; border: string;
} {
  if (d === "bullish") {
    return {
      bg: "bg-emerald-500/10",
      text: "text-emerald-700 dark:text-emerald-300",
      border: "border-emerald-500/40",
    };
  }
  if (d === "bearish") {
    return {
      bg: "bg-rose-500/10",
      text: "text-rose-700 dark:text-rose-300",
      border: "border-rose-500/40",
    };
  }
  return {
    bg: "bg-muted",
    text: "text-muted-foreground",
    border: "border-border",
  };
}
