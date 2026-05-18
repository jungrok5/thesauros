/**
 * BookVerdict — top-of-page conclusion. Regression suite for the
 * 매복 단계 (ambush) classification:
 *
 *   국보디자인 2026-05-22 had STRONG_BUY action + 쌍바닥 +3% fresh
 *   pattern, BUT also had:
 *     - MA 10/20/60 spread ~2.6% (convergence)
 *     - volume_case 12 (수렴기 거래량 감소, vol_ratio 0.62)
 *     - last candle body 14% with 68% lower wick (교수형)
 *   The verdict should be "🟡 매복" not "🟢 강한 매수" — entering this
 *   ticker right now is buying a sideways box, not a fresh breakout.
 */
import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(cleanup);
import { BookVerdict } from "@/components/book-verdict";
import type { AnalysisResult } from "@/lib/types/analysis";

function makeResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    ticker: "066620.KQ",
    as_of: "2026-05-22",
    last_close: 24450,
    rows: 266,
    action: "STRONG_BUY",
    book_score: 1.0,
    trend: {
      daily: null,
      weekly: {
        timeframe: "weekly",
        price: 24450,
        ma_10: 23465,
        above_ma_10: true,
        ma_10_slope_up: true,
        ma_240: 18085,
        above_ma_240: true,
        alignment_score: 1.0,
        overall_score: 1.0,
        label: "강세",
      },
      monthly: {
        timeframe: "monthly",
        price: 24450,
        ma_10: 22420,
        above_ma_10: true,
        ma_10_slope_up: true,
        ma_240: null,
        above_ma_240: null,
        alignment_score: 0.5,
        overall_score: 0.81,
        label: "강세",
      },
      book_signal: "BUY",
      book_reason: "월봉/주봉 10MA 위 + 정배열 → 추세 살아있음",
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

describe("BookVerdict — 매복 (ambush) classification", () => {
  it("flips a STRONG_BUY into 매복 when 2+ of (setup pattern, drying volume, indecision candle, tight box) hit", () => {
    // 국보디자인 2026-05-22 exact reproduction:
    //   - no explicit setup pattern (60-MA spread too wide)
    //   - volume case 7 (drying, bullish accumulation interp)
    //   - indecision candle (교수형)
    //   - tight box 4 % over the last 4 weeks
    //   → 3-of-4 signals → 매복 fires.
    const r = makeResult({
      action: "STRONG_BUY",
      last_close: 24450,
      patterns: [],
      volume_case: {
        case: 7, label_kr: "급등 중 거래량 감소 (세력 매집 완료)",
        direction: "bullish", confidence: 0.78,
        reason: "상승 추세인데 거래량 -38%",
      },
      last_candle: {
        date: "2026-05-22", open: 24600, high: 24800, low: 23700, close: 24450,
        volume: 21778, body_pct: 0.14, upper_wick_pct: 0.18, lower_wick_pct: 0.68,
        close_position: 0.32, is_bullish: false, tags: ["교수형"], in_safe_zone_75: null,
      },
      consolidation_ratio: 0.041,
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/매복.*포킹 대기/)).toBeInTheDocument();
    expect(screen.getByText(/이평선 수렴/)).toBeInTheDocument();
    expect(screen.getByText(/포킹 발사.*까지 매복/)).toBeInTheDocument();
  });

  it("does NOT misfire 매복 when only ONE indicator is present", () => {
    const r = makeResult({
      action: "STRONG_BUY",
      patterns: [],
      volume_case: {
        case: 12, label_kr: "수렴기 거래량 감소",
        direction: "bullish", confidence: 0.62,
        reason: "",
      },
      // No indecision candle, no tight box, no setup pattern → only 1 hit
      last_candle: {
        date: "2026-05-22", open: 100, high: 102, low: 99.5, close: 101.8,
        volume: 50000, body_pct: 0.72, upper_wick_pct: 0.08, lower_wick_pct: 0.20,
        close_position: 0.92, is_bullish: true, tags: ["장대양봉"], in_safe_zone_75: true,
      },
      consolidation_ratio: 0.15,   // wide swings, not a box
    });
    render(<BookVerdict result={r} />);
    expect(screen.queryByText(/매복.*포킹/)).toBeNull();
  });

  it("keeps the stale-pattern amber verdict (different code path) intact", () => {
    const r = makeResult({
      action: "STRONG_BUY",
      patterns: [
        {
          kind: "쌍바닥", direction: "bullish", confidence: 0.9, completed: true,
          detected_at: "2025-10-31",
          entry: 50000, stop: 45000, target: 80000,
          reason: "쌍바닥",
          timeframe: "weekly",
          extra: { neckline: 50000 },
        },
      ],
      last_close: 100500, // +101% past breakout
    });
    render(<BookVerdict result={r} />);
    // Stale-pattern verdict should fire BEFORE 매복 check.
    expect(
      screen.getByText(/진입 자리 지남|진입 자리는 이미/),
    ).toBeInTheDocument();
  });

  it("HOLD branch — IONQ-style catalyst-after narrative", () => {
    const r = makeResult({
      ticker: "IONQ",
      action: "HOLD",
      book_score: 0.24,
      last_close: 49.31,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 49.31, ma_10: 40.23,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 32.61, above_ma_240: true,
          alignment_score: 0.20, overall_score: 0.76, label: "강세",
        },
        monthly: {
          timeframe: "monthly", price: 49.31, ma_10: 35.0,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: null, above_ma_240: null,
          alignment_score: 0.5, overall_score: 0.75, label: "강세",
        },
        book_signal: "HOLD", book_reason: "보유 평가",
      },
      patterns: [
        {
          kind: "장대양봉 catalyst", direction: "bullish", confidence: 0.80,
          completed: true, detected_at: "2026-04-17",
          entry: 46.09, stop: 32.71, target: 81.76,
          reason: "장대양봉 +63%",
          timeframe: "weekly",
          extra: {
            catalyst_open: 28.25, catalyst_close: 46.09, catalyst_high: 46.69,
            q25: 32.71, q50: 37.17, q75: 41.63,
            bars_since: 5, runup_since: 7.0,
          },
        },
      ],
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/한 줄 평.*관망/)).toBeInTheDocument();
    // 240MA above by computed pct
    expect(screen.getByText(/240MA.*\+51%.*죽지 않은/)).toBeInTheDocument();
    // Catalyst anchor + runup_since
    expect(screen.getByText(/장대양봉 catalyst.*5주 전.*\+7%/)).toBeInTheDocument();
    // 25% absolute level as stop
    expect(screen.getByText(/25% 절대자리.*32\.71/)).toBeInTheDocument();
    // Weekly 10MA trailing stop guidance
    expect(screen.getByText(/주봉 10MA.*40\.23.*이탈/)).toBeInTheDocument();
    // Next decision point (Friday close)
    expect(screen.getByText(/다음 결정 시점.*금요일/)).toBeInTheDocument();
  });

  it("HOLD branch — stale catalyst surfaces '한참 지났음' verdict", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 100,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 100, ma_10: 80,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 50, above_ma_240: true,
          alignment_score: 0.5, overall_score: 0.6, label: "강세",
        },
        monthly: null,
        book_signal: "HOLD", book_reason: "",
      },
      patterns: [
        {
          kind: "장대양봉 catalyst", direction: "bullish", confidence: 0.85,
          completed: true, detected_at: "2025-09-01",
          entry: 60, stop: 50, target: 100,
          reason: "",
          timeframe: "weekly",
          extra: { catalyst_close: 60, q25: 50, bars_since: 30, runup_since: 66.7 },
        },
      ],
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/장대양봉 catalyst.*\+67%.*한참 지났음/)).toBeInTheDocument();
  });

  it("HOLD branch — no catalyst, only 240MA gate narrative", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 80,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 80, ma_10: 75,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 50, above_ma_240: true,
          alignment_score: 0.3, overall_score: 0.4, label: "강세",
        },
        monthly: null,
        book_signal: "HOLD", book_reason: "",
      },
      patterns: [],
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/240MA.*\+60%.*죽지 않은/)).toBeInTheDocument();
    expect(screen.queryByText(/catalyst/)).toBeNull();
    expect(screen.getByText(/다음 결정 시점.*금요일/)).toBeInTheDocument();
  });

  it("HOLD branch — 240MA below renders 죽은 차트", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 40,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 40, ma_10: 45,
          above_ma_10: false, ma_10_slope_up: false,
          ma_240: 50, above_ma_240: false,
          alignment_score: -0.5, overall_score: -0.6, label: "약세",
        },
        monthly: null,
        book_signal: "HOLD", book_reason: "",
      },
      patterns: [],
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/240MA.*아래.*죽은 차트/)).toBeInTheDocument();
  });

  it("renders 🟢 강한 매수 for a clean fresh-pattern setup", () => {
    const r = makeResult({
      action: "STRONG_BUY",
      patterns: [
        {
          kind: "쌍바닥", direction: "bullish", confidence: 0.9, completed: true,
          detected_at: "2026-05-22",
          entry: 24450, stop: 19000, target: 30000,
          reason: "쌍바닥",
          timeframe: "weekly",
          extra: { neckline: 23800 }, // current 24450 vs 23800 = +2.7% fresh
        },
      ],
      volume_case: {
        case: 3, label_kr: "바닥권 거래량 폭증",
        direction: "bullish", confidence: 0.85, reason: "",
      },
      last_candle: {
        date: "2026-05-22", open: 23800, high: 24500, low: 23700, close: 24450,
        volume: 80000, body_pct: 0.81, upper_wick_pct: 0.06, lower_wick_pct: 0.12,
        close_position: 0.94, is_bullish: true, tags: ["장대양봉"], in_safe_zone_75: true,
      },
      consolidation_ratio: 0.18,  // wide swings during breakout, not a box
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/강한 매수/)).toBeInTheDocument();
  });
});
