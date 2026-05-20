/**
 * Macro indicator interpretation — converts raw values into a short
 * "이 지표가 주식에 어떻게" line. Two functions:
 *
 *   tickerHint(symbol)   — for the MarketTicker top strip. Returns a
 *                          tiny static rule ("VIX ↑ → 주식 ↓") that
 *                          doesn't change with the value. Mobile-tight.
 *
 *   indicatorVerdict(key, state, value, yoyPct)
 *                       — for the 핵심 거시 지표 cards. Builds a
 *                          two-line verdict: (a) directional rule of
 *                          this indicator vs equity market, (b) what
 *                          the current state means + action.
 *
 * Both are pure (no React, no fetch) — vitest-friendly. Centralizes
 * the macro→equity mental model so the dashboard isn't just a wall of
 * numbers.
 */

import type { Tone } from "@/lib/market-signals-interpret";

// ─────────────────────────────────────────────────────────────────────
// MarketTicker static hints
// ─────────────────────────────────────────────────────────────────────

/**
 * One-line static rule per ticker symbol. Returns null when the
 * symbol is itself an index/stock (KOSPI, S&P) — interpreting a
 * price index against the stock market is tautological.
 */
export function tickerHint(symbol: string): string | null {
  switch (symbol) {
    // Stock/index prices — no interpretation needed (they ARE the market).
    case "^KS11":
    case "^KQ11":
    case "^GSPC":
    case "^IXIC":
    case "^DJI":
      return null;
    case "^VIX":
      return "↑ 공포 ↑ → 주식 ↓ (20+ 경계)";
    case "KRW=X":
      return "↑ 환율 ↑ = 원화 약세 → 수출주 ↑ / 내수 ↓";
    case "^TNX":
      return "↑ 금리 ↑ → 성장주 / 빅테크 ↓";
    case "CL=F":
      return "↑ 유가 ↑ → 인플레 부담, 에너지주 ↑";
    case "GC=F":
      return "↑ 금 ↑ → 위험 회피 신호, 주식엔 부정";
    case "BTC-USD":
      return "↑ 위험자산 선호 ↑ → 주식 ↑ (동행)";
    default:
      return null;
  }
}

// ─────────────────────────────────────────────────────────────────────
// 핵심 거시 지표 verdict
// ─────────────────────────────────────────────────────────────────────

export type IndicatorState = "BULL" | "NEUTRAL" | "CAUTION" | "BEAR";

export interface IndicatorVerdict {
  /** 1-line static rule of this indicator vs equity market. */
  impact: string;
  /** State-specific interpretation + action. */
  action: string;
  tone: Tone;
}

const STATE_TONE: Record<IndicatorState, Tone> = {
  BULL: "good",
  NEUTRAL: "neutral",
  CAUTION: "warn",
  BEAR: "bad",
};

/**
 * Indicator-key directional rule + state-driven action. The `value`
 * + `yoyPct` aren't always used — for some indicators (정성 state)
 * just the BULL/BEAR label is enough.
 */
export function indicatorVerdict(
  key: string,
  state: IndicatorState,
  value: number | null,
  yoyPct: number | null,
): IndicatorVerdict {
  const tone = STATE_TONE[state];
  const k = key.toLowerCase();

  // 1) Inflation family — CPI / PPI / TIPS breakeven.
  if (k === "cpi" || k.startsWith("cpi_")) {
    return {
      impact: "↑ 인플레 ↑ → Fed 긴축 압박 → 주식 ↓ (특히 성장주)",
      action: actionByState(state, {
        BULL: "인플레 진정 추세. 금리 인하 기대 ↑ → 매수 우호.",
        NEUTRAL: "목표(2%) 근처에서 횡보. 시장은 다음 데이터 대기.",
        CAUTION: "재반등 우려. 다음 CPI 발표 전 신규 매수 보수적.",
        BEAR: "인플레 재가속. Fed 매파 전환 → 성장주 회피 + 비중 축소.",
      }),
      tone,
    };
  }

  if (k === "ppi" || k.startsWith("ppi_")) {
    return {
      impact: "↑ 생산자물가 ↑ → 향후 CPI 압박 (선행 지표)",
      action: actionByState(state, {
        BULL: "공급망 안정. CPI 둔화 전조 → 주식 우호.",
        NEUTRAL: "혼조. CPI 와 함께 봐야 의미.",
        CAUTION: "원가 부담 ↑. 영업이익률 압박 가능.",
        BEAR: "공급망 충격 가능. 마진 압박 대비.",
      }),
      tone,
    };
  }

  if (k === "tips_breakeven_10y" || k === "tips_spread") {
    return {
      impact: "↑ 기대 인플레 ↑ → 명목 금리 ↑ → 성장주 ↓",
      action: actionByState(state, {
        BULL: "기대 인플레 안정. 채권+주식 동반 가능.",
        NEUTRAL: "정상 범위 (2-2.5%).",
        CAUTION: "기대 인플레 ↑ — 금리 상승 압박.",
        BEAR: "스태그플레이션 risk. 방어주 / 현금 비중.",
      }),
      tone,
    };
  }

  // 2) Rate family — Fed funds / 10Y / real rate.
  if (k === "fed_funds_rate") {
    return {
      impact: "↑ 정책금리 ↑ → 모든 자산 valuation 압박",
      action: actionByState(state, {
        BULL: "동결 / 인하 기조. 주식 valuation 회복.",
        NEUTRAL: "현 수준 유지. 데이터 의존.",
        CAUTION: "추가 인상 가능성. 성장주 비중 축소.",
        BEAR: "긴축 사이클 지속. 단기 채권 + 방어주.",
      }),
      tone,
    };
  }

  if (k === "real_rate_10y") {
    return {
      impact: "↑ 실질금리 ↑ → 주식·금 valuation ↓ (가장 무거운 지표)",
      action: actionByState(state, {
        BULL: "실질금리 하락 — 주식 우호 환경.",
        NEUTRAL: "1-1.5% 범위. 통상 수준.",
        CAUTION: "2%+ — 성장주 부담. 가치주 / 배당주 선호.",
        BEAR: "2.5%+ — 위험자산 강한 압박. 비중 축소.",
      }),
      tone,
    };
  }

  if (k === "yield_curve_10y_2y" || k === "yield_curve_10y_3m" || k === "yield_curve") {
    const inverted = value != null && value < 0;
    return {
      impact: "역전 (음수) → 경기 침체 신호 (12-18개월 lead)",
      action: actionByState(state, {
        BULL: "정상 spread. 경기 확장 신호.",
        NEUTRAL: inverted ? "역전 지속 중. 침체 risk 누적." : "역전 회복 중.",
        CAUTION: "역전 깊어짐. 침체 시계 가속.",
        BEAR: "역전 + 다른 침체 신호 동반. 방어 비중 ↑.",
      }),
      tone,
    };
  }

  // 3) Credit & liquidity — HY spread / M2 / DXY.
  if (k === "credit_spread_hy" || k === "hy_spread") {
    return {
      impact: "↑ 정크채 스프레드 ↑ → 신용 경색 → 주식 ↓",
      action: actionByState(state, {
        BULL: "스프레드 좁음. risk-on 환경, 주식 매수 우호.",
        NEUTRAL: "통상 범위 (3-5%).",
        CAUTION: "스프레드 확대 — 신용 risk 누적. 비중 축소 검토.",
        BEAR: "급격 확대 (6%+) — 침체 / 위기 신호. 현금 / 국채 비중.",
      }),
      tone,
    };
  }

  if (k === "m2_supply" || k === "m2") {
    return {
      impact: "↑ 유동성 ↑ → 자산가격 ↑ (주식 + 부동산)",
      action: actionByState(state, {
        BULL: "유동성 공급 ↑. 주식 우호.",
        NEUTRAL: "정상 증가 속도.",
        CAUTION: "긴축 모드 — 자산가격 압박.",
        BEAR: "유동성 축소. 위험자산 회피.",
      }),
      tone,
    };
  }

  if (k === "dxy" || k === "us_dxy") {
    return {
      impact: "↑ 달러 강세 → 이머징 / 원자재 / 미국 외 ↓",
      action: actionByState(state, {
        BULL: "달러 약세 — 이머징·코스피 우호.",
        NEUTRAL: "100-105 정상 범위.",
        CAUTION: "달러 강세 — 한국 / 신흥국 자금 유출.",
        BEAR: "달러 폭등 — 글로벌 risk-off.",
      }),
      tone,
    };
  }

  // 4) Sentiment / volatility.
  if (k === "vix" || k === "vix_state") {
    return {
      impact: "↑ VIX ↑ = 공포 ↑ → 주식 ↓ (역의 상관)",
      action: actionByState(state, {
        BULL: "VIX < 20 — 시장 안정. 매수 자리 적극.",
        NEUTRAL: "20-25 — 보통 변동성.",
        CAUTION: "25-30 — 변동성 ↑. 매수 분할.",
        BEAR: "30+ — 패닉. 책 정신: 자본 보전 1순위, 적극 매수 X.",
      }),
      tone,
    };
  }

  // Default — generic verdict using state only.
  return {
    impact: "현재 상태를 시장 신호로 참고.",
    action: actionByState(state, {
      BULL: "주식 우호 환경.",
      NEUTRAL: "중립 — 추세 신호 우선.",
      CAUTION: "주의 — 분할 진입.",
      BEAR: "위험 — 비중 축소 검토.",
    }),
    tone,
  };
}

function actionByState(
  state: IndicatorState,
  map: Record<IndicatorState, string>,
): string {
  return map[state];
}
