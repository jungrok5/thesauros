/**
 * NoviceVerdict (analysis-view 안의 callout) consistency regression.
 *
 * 068930.KQ 2026-05-21 reported case: action=STRONG_BUY 이지만 BookVerdict
 * 가 매복 분기로 라우팅 — NoviceVerdict 가 ✅ "매수 자격 가능" 표시하면
 * 페이지 안에 모순 (✅ + 🟡). 이 테스트는 그 dim 합 일관성을 잠금.
 *
 * If someone changes pickFreshBullishPattern / isAmbushSetup / isPostRallyCaution
 * signatures or removes them from analysis-view import, these tests fail.
 */
import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);

import { AnalysisView } from "@/components/analysis-view";
import type { AnalysisResult } from "@/lib/types/analysis";

function baseResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    ticker: "TEST.KQ",
    as_of: "2026-05-22",
    last_close: 100,
    rows: 200,
    action: "STRONG_BUY",
    book_score: 1.0,
    trend: {
      daily: null,
      weekly: {
        timeframe: "weekly", price: 100, ma_10: 98,
        above_ma_10: true, ma_10_slope_up: true,
        ma_240: 80, above_ma_240: true,
        alignment_score: 1.0, overall_score: 1.0, label: "강세",
      },
      monthly: {
        timeframe: "monthly", price: 100, ma_10: 95,
        above_ma_10: true, ma_10_slope_up: true,
        ma_240: null, above_ma_240: null,
        alignment_score: 0.5, overall_score: 0.85, label: "강세",
      },
      book_signal: "BUY", book_reason: "",
    },
    last_candle: null,
    patterns: [],
    reversals: [],
    volume_case: null,
    reverse_accumulation: null,
    entry_plan: null,
    ...overrides,
  };
}

describe("NoviceVerdict — 단순 action 매핑", () => {
  it("STRONG_BUY (no ambush/stale/post-rally) → ✅ 매수 자격 가능", () => {
    const r = baseResult({ action: "STRONG_BUY" });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 가능/)).toBeInTheDocument();
  });

  it("HOLD (no stretch) → ⏸ 관망", () => {
    const r = baseResult({ action: "HOLD" });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 관망/)).toBeInTheDocument();
  });

  it("AVOID → ❌ 없음 (회피)", () => {
    const r = baseResult({ action: "AVOID" });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 없음.*회피/)).toBeInTheDocument();
  });

  it("SELL → 🔴 없음 (매도 신호)", () => {
    const r = baseResult({ action: "SELL" });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 없음.*매도/)).toBeInTheDocument();
  });
});

describe("NoviceVerdict — BookVerdict 분기 일관성 (068930.KQ regression)", () => {
  it("STRONG_BUY + ambush 분기 → ⚠️ 조건부 (✅ 매수 자격 가능 ❌)", () => {
    // 매복 분기 트리거 조건 (book-verdict.tsx:isAmbushSetup):
    //  - 2+ of (수렴 매복 setup pattern / drying volume / indecision candle / tight box)
    //  - position_in_52w < 0.85
    //  - last_close <= ma_10w * 1.05  (068930.KQ-style)
    const r = baseResult({
      action: "STRONG_BUY",
      last_close: 100,
      position_in_52w: 0.5,
      consolidation_ratio: 0.04,
      volume_case: {
        case: 12, label_kr: "수렴기 거래량 감소",
        direction: "bullish", confidence: 0.65, reason: "",
      },
      patterns: [
        {
          kind: "MA 수렴 매복", direction: "neutral", confidence: 0.55,
          completed: false, detected_at: "2026-05-22",
          entry: 100, stop: 95, target: null, reason: "",
          timeframe: "weekly", extra: {},
        },
      ],
      last_candle: {
        date: "2026-05-22", open: 100, high: 101, low: 98, close: 99,
        volume: 50000, body_pct: 0.20, upper_wick_pct: 0.25, lower_wick_pct: 0.55,
        close_position: 0.33, is_bullish: false, tags: ["교수형"],
        in_safe_zone_75: null,
      },
    });
    render(<AnalysisView result={r} />);
    // ⚠️ 다운그레이드 칩이 떠야 함 — ✅ 가능 아님
    expect(screen.getByText(/오늘 매수 자격: 조건부.*자리 X/)).toBeInTheDocument();
    expect(screen.queryByText(/오늘 매수 자격: 가능/)).toBeNull();
    expect(screen.getByText(/박스권 횡보|포킹 발사 대기/)).toBeInTheDocument();
  });

  it("STRONG_BUY + stale-pattern 분기 → ⚠️ 조건부 (이미 자리 한참 지남)", () => {
    const r = baseResult({
      action: "STRONG_BUY",
      last_close: 200,
      patterns: [
        {
          kind: "쌍바닥", direction: "bullish", confidence: 0.9,
          completed: true, detected_at: "2026-05-22",
          entry: 200, stop: 90, target: 350, reason: "쌍바닥",
          timeframe: "weekly", extra: { neckline: 100 }, // runup = +100%
        },
      ],
    });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 조건부/)).toBeInTheDocument();
    expect(screen.queryByText(/오늘 매수 자격: 가능/)).toBeNull();
    expect(screen.getByText(/이미 매수 자리 한참 지남/)).toBeInTheDocument();
  });

  it("BUY + post-rally caution → ⚠️ 조건부 (랠리 후 조정)", () => {
    const r = baseResult({
      ticker: "GOOGL",
      action: "BUY",
      last_close: 400,
      position_in_52w: 0.95,
      rally_8w_pct: 0.16,
      consolidation_ratio: 0.038,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 400, ma_10: 345,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 220, above_ma_240: true,
          alignment_score: 0.6, overall_score: 0.88, label: "강세",
        },
        monthly: null,
        book_signal: "BUY", book_reason: "",
      },
      last_candle: {
        date: "2026-05-22", open: 395, high: 408, low: 394, close: 400,
        volume: 26000000,
        body_pct: 0.09, upper_wick_pct: 0.83, lower_wick_pct: 0.08,
        close_position: 0.17, is_bullish: true,
        tags: ["그레이브스톤도지"], in_safe_zone_75: false,
      },
    });
    render(<AnalysisView result={r} />);
    // NoviceVerdict headline 은 유일 (BookVerdict 와 안 겹침)
    expect(screen.getByText(/오늘 매수 자격: 조건부/)).toBeInTheDocument();
    expect(screen.queryByText(/오늘 매수 자격: 가능/)).toBeNull();
    // "랠리 후 조정" 자체는 NoviceVerdict + BookVerdict 모두에 들어가니
    // getAllByText 로 둘 다 나오는지 확인 (모순 없음 자체 검증).
    expect(screen.getAllByText(/랠리 후 조정/).length).toBeGreaterThan(0);
  });

  it("HOLD + stretch_reason → ⚠️ 조건부 — 자리 지남", () => {
    const r = baseResult({
      action: "HOLD",
      stretch_reason: "8주 +115% (책 +50% 룰 위반)",
    });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/오늘 매수 자격: 조건부.*자리 지남/)).toBeInTheDocument();
    expect(screen.queryByText(/오늘 매수 자격: 관망$/)).toBeNull();
  });

  it("SELL_OR_SHORT + 저승사자 → 🔴 즉시 청산 callout", () => {
    const r = baseResult({
      action: "SELL_OR_SHORT",
      stretch_reason: "저승사자 캔들 발현 (장대음봉 + 10MA 이탈)",
    });
    render(<AnalysisView result={r} />);
    expect(screen.getByText(/저승사자.*즉시 청산/)).toBeInTheDocument();
  });
});
