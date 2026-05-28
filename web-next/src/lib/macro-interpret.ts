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
  /**
   * Optional plain-Korean note explaining how this indicator's move
   * tends to ripple into the Korean economy (대출이자 / 환율 / 물가 /
   * 수출입 등). Only filled for the indicators where the KR-side story
   * is non-obvious to a beginner — Fed 금리, 실질금리, 달러지수, 금.
   * Rendered as the 🇰🇷 line in IndicatorCard.
   */
  krEconomy?: string;
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
      impact: "↑ 미국 금리 ↑ → 빌리는 돈이 비싸짐 → 기업 이익·주가 ↓",
      action: actionByState(state, {
        BULL: "동결 / 인하 분위기. 주식에 우호.",
        NEUTRAL: "현 수준 유지. 다음 경제지표 보고 판단.",
        CAUTION: "추가 인상 가능성. 빚 많은 기업·성장주 부담.",
        BEAR: "긴축 지속. 위험 자산 비중 축소 검토.",
      }),
      tone,
      krEconomy:
        "한국은행은 한국 금리를 보통 미국 금리 ±0.5%p 범위로 따라간다. " +
        "미국이 올리면 한국도 올림 → 대출이자 ↑ → 부동산·소비 위축, " +
        "내림 → 가계 부담 ↓ + 내수·부동산 회복 기대.",
    };
  }

  if (k === "real_rate_10y") {
    return {
      impact:
        "↑ 실질금리(물가 빼고 본 진짜 금리) ↑ → 주식·금 모두 매력 ↓",
      action: actionByState(state, {
        BULL: "실질금리 하락 — 주식·금 둘 다 우호.",
        NEUTRAL: "1-1.5% 안. 평소 수준.",
        CAUTION: "2% 넘음 — 빚 많은 회사·신생 기업 부담 ↑.",
        BEAR: "2.5%+ — 위험 자산 전반 압박, 안전 자산 선호 ↑.",
      }),
      tone,
      krEconomy:
        "실질금리 ↑ 이면 글로벌 자금이 미국 채권에 몰림 → 한국 주식에서 " +
        "외국인 자금 이탈 + 원/달러 환율 ↑ (원화 약세) → 수입물가 ↑, " +
        "수출주는 가격 경쟁력 ↑.",
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
      impact:
        "↑ 달러 강세 → 한국·신흥국 주식·원자재 가격 ↓ (자금이 미국으로)",
      action: actionByState(state, {
        BULL: "달러 약세 — 코스피·신흥국 우호.",
        NEUTRAL: "100-105 평소 범위.",
        CAUTION: "달러 강세 — 한국 등 신흥국 자금 빠짐.",
        BEAR: "달러 폭등 — 전 세계 위험 회피 모드.",
      }),
      tone,
      krEconomy:
        "달러 강세는 곧 원/달러 환율 ↑ (원화 약세). " +
        "수입 원자재·기름값 ↑ → 물가 ↑, 해외여행·유학 부담 ↑. " +
        "반대로 수출 대기업(삼성·현대 등) 은 가격 경쟁력 ↑ → 단기 이익 우호.",
    };
  }

  if (k === "usdkrw" || k === "krwusd" || k === "krw_x") {
    return {
      impact:
        "↑ 원/달러 환율 ↑ = 원화 약세 → 수출주 ↑ / 수입·내수주 ↓",
      action: actionByState(state, {
        BULL: "환율 안정. 한국 자산 외국인 매수 우호.",
        NEUTRAL: "1,300원대 안 — 평소 변동성.",
        CAUTION: "1,400원 근처 — 수입물가·외국인 이탈 압박.",
        BEAR: "1,450원 + 외환 위기 신호. 방어 우선.",
      }),
      tone,
      krEconomy:
        "환율 ↑ 면 휘발유·식료품 같은 수입 비중 큰 품목 가격 ↑ → 가계 물가 부담. " +
        "수출 대기업 매출은 원화 환산 늘어나서 단기 호재지만 " +
        "장기적으로 외국인 투자자가 한국 주식·채권을 팔고 빠져나가는 흐름이 강해짐.",
    };
  }

  // 4) Commodity / safe-haven.
  if (k === "gold") {
    return {
      impact:
        "↑ 금 ↑ → 보통 위험 회피 신호 (전쟁·불황 우려) → 주식 ↓ 가능",
      action: actionByState(state, {
        BULL: "금 상승 — 보통 인플레 헷지 + 안전자산 수요.",
        NEUTRAL: "횡보 — 명확한 신호 없음.",
        CAUTION: "급등 — 시장이 큰 risk 를 가격에 반영하는 중.",
        BEAR: "급락 — 위험 자산 선호 회복 신호.",
      }),
      tone,
      krEconomy:
        "한국에서는 금이 인플레·환율 헷지 수단. " +
        "금값 ↑ + 원화 약세가 동반되면 국내 금 ETF·금 통장이 더 빠르게 오름. " +
        "다만 금 강세 = 글로벌 risk-off 분위기라 한국 주식엔 보통 역풍.",
    };
  }

  if (k === "usdjpy") {
    return {
      impact:
        "↑ 달러/엔 환율 ↑ = 엔 약세 → 일본 수출주 ↑ / 한국 수출주는 가격경쟁력 ↓",
      action: actionByState(state, {
        BULL: "엔 강세 — 한국 수출주 상대 우위.",
        NEUTRAL: "현 수준 안정.",
        CAUTION: "엔 약세 진행 — 자동차·조선 등 한일 경쟁 업종 부담.",
        BEAR: "엔 폭락 — 한국 수출주 가격 경쟁력 큰 압박.",
      }),
      tone,
      krEconomy:
        "원/엔 환율도 자연히 영향. 엔 약세 = 일본 여행·일본 제품 싸짐 → 한국인 일본 소비 ↑. " +
        "반대로 일본 관광객 한국 방문 매력 ↓ → 명동·면세 매출에 단기 역풍.",
    };
  }

  // 5) Sentiment / volatility.
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
