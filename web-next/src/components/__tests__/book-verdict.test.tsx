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

  it("랠리 후 조정 branch — GOOGL-style top with upper-wick reversal", () => {
    const r = makeResult({
      ticker: "GOOGL",
      action: "BUY",
      book_score: 0.6,
      last_close: 396.94,
      position_in_52w: 0.95,
      rally_8w_pct: 0.16,
      consolidation_ratio: 0.038,
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 396.94, ma_10: 345.46,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 220.15, above_ma_240: true,
          alignment_score: 0.6, overall_score: 0.88, label: "강세",
        },
        monthly: null,
        book_signal: "BUY", book_reason: "",
      },
      patterns: [],
      last_candle: {
        date: "2026-05-18", open: 395.69, high: 408.61, low: 394.53, close: 396.94,
        volume: 26_000_000,
        body_pct: 0.09, upper_wick_pct: 0.83, lower_wick_pct: 0.08,
        close_position: 0.17, is_bullish: true,
        tags: ["그레이브스톤도지"], in_safe_zone_75: false,
      },
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/랠리 후 조정.*반전 주의/)).toBeInTheDocument();
    expect(screen.getByText(/8주 \+16% 랠리.*52주 신고가 95%/)).toBeInTheDocument();
    expect(screen.getByText(/그레이브스톤도지.*반전 주의/)).toBeInTheDocument();
    expect(screen.getByText(/신규 매수 자리 아님/)).toBeInTheDocument();
    // Must NOT misfire 매복 (semantically opposite)
    expect(screen.queryByText(/매복 · 포킹 대기/)).toBeNull();
  });

  it("랠리 후 조정 does NOT fire when 52w position low (mid-range box)", () => {
    const r = makeResult({
      action: "STRONG_BUY",
      position_in_52w: 0.55,  // mid-range — could be 매복 territory
      rally_8w_pct: 0.05,
      consolidation_ratio: 0.04,
      patterns: [
        {
          kind: "MA 수렴 매복", direction: "neutral", confidence: 0.55,
          completed: false, detected_at: "2026-05-22",
          entry: 100, stop: 90, target: null, reason: "",
          timeframe: "weekly", extra: {},
        },
      ],
      last_candle: {
        date: "2026-05-22", open: 100, high: 101, low: 98, close: 99,
        volume: 50000, body_pct: 0.20, upper_wick_pct: 0.25, lower_wick_pct: 0.55,
        close_position: 0.33, is_bullish: false, tags: ["교수형"], in_safe_zone_75: null,
      },
      volume_case: {
        case: 12, label_kr: "수렴기 거래량 감소",
        direction: "bullish", confidence: 0.65, reason: "",
      },
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/매복.*포킹 대기/)).toBeInTheDocument();
    expect(screen.queryByText(/랠리 후 조정/)).toBeNull();
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

  // ── 4등분선 zone narrative (book p218-223, Phase 2 P1) ───────────
  it("quarter_zone=safe75 → '안전지대' line in HOLD verdict", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 50,
      quarter_zone: "safe75",
      patterns: [{
        kind: "장대양봉 catalyst", direction: "bullish", confidence: 0.8,
        completed: true, detected_at: "2026-03-15",
        entry: 40, stop: 35, target: 60, reason: "", timeframe: "weekly",
        extra: {
          catalyst_open: 30, catalyst_close: 48,
          q25: 34.5, q50: 39, q75: 43.5,
          bars_since: 8, runup_since: 4,
        },
      }],
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 50, ma_10: 45,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 30, above_ma_240: true,
          alignment_score: 0.6, overall_score: 0.7, label: "강세",
        },
        monthly: null,
        book_signal: "HOLD", book_reason: "",
      },
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/4등분선 75 % 안전지대/)).toBeInTheDocument();
  });

  it("quarter_zone=broken → '절대자리 깨짐' callout", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 32,
      quarter_zone: "broken",
      patterns: [{
        kind: "장대양봉 catalyst", direction: "bullish", confidence: 0.8,
        completed: true, detected_at: "2026-03-15",
        entry: 40, stop: 35, target: 60, reason: "", timeframe: "weekly",
        extra: { catalyst_open: 30, catalyst_close: 48, q25: 34.5 },
      }],
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 32, ma_10: 35,
          above_ma_10: false, ma_10_slope_up: false,
          ma_240: 30, above_ma_240: true,
          alignment_score: 0.0, overall_score: 0.0, label: "관망",
        },
        monthly: null,
        book_signal: "HOLD", book_reason: "",
      },
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/4등분선 25 % 절대자리 깨짐/)).toBeInTheDocument();
  });

  // ── 장대음봉 / 저승사자 branches (P0a in Phase 2) ────────────────
  it("장대음봉 stretch_reason → 장대음봉 · 매도 압력 verdict", () => {
    const r = makeResult({
      ticker: "003555.KS",
      action: "HOLD",
      last_close: 72200,
      stretch_reason: "마지막 봉 장대음봉 — 책 룰: 매도 압력",
      patterns: [],
      entry_plan: null,
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByRole("heading", { name: /장대음봉.*매도 압력/ }))
      .toBeInTheDocument();
    expect(screen.getByText(/장대음봉 출현/)).toBeInTheDocument();
    expect(screen.queryByText(/한 줄 평 · 관망/)).toBeNull();
  });

  it("저승사자 stretch_reason → 저승사자 · 청산 verdict (red card)", () => {
    const r = makeResult({
      action: "SELL_OR_SHORT",
      stretch_reason: "저승사자 캔들 (장대음봉 + 주봉 10MA 하향 이탈)",
      patterns: [],
      entry_plan: null,
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByRole("heading", { name: /저승사자.*청산/ }))
      .toBeInTheDocument();
    expect(screen.getByText(/즉시 청산/)).toBeInTheDocument();
  });

  it("invalidated pattern surfaces as warning on every verdict color", () => {
    const r = makeResult({
      action: "STRONG_BUY",
      last_close: 72200,
      patterns: [
        {
          kind: "쌍바닥", direction: "bullish", confidence: 0.85,
          completed: true, detected_at: "2026-04-03",
          entry: 72200, stop: 65000, target: 100600,
          reason: "쌍바닥", timeframe: "weekly",
          extra: { neckline: 81000 },
          invalidated: true,
          invalidation_reason: "close 72,200 < neckline 81,000 (돌파선 재이탈)",
        },
      ],
      volume_case: {
        case: 3, label_kr: "바닥권 거래량 폭증",
        direction: "bullish", confidence: 0.85, reason: "",
      },
      last_candle: {
        date: "2026-05-22", open: 73000, high: 74500, low: 71800, close: 72500,
        volume: 80000, body_pct: 0.40, upper_wick_pct: 0.20, lower_wick_pct: 0.40,
        close_position: 0.32, is_bullish: false, tags: [], in_safe_zone_75: false,
      },
    });
    render(<BookVerdict result={r} />);
    expect(screen.getByText(/쌍바닥 패턴 무효화/)).toBeInTheDocument();
    expect(screen.getByText(/돌파선 재이탈/)).toBeInTheDocument();
  });

  // ── 추세 유효 · 자리 지남 (analyzer stretch downgrade) ───────────
  // The analyzer flips BUY/STRONG_BUY → HOLD and stamps stretch_reason
  // when the chart is past the book's neat entry zone (rally ≥ 50 %,
  // 240MA distance > +100 %, or 52w pos ≥ 0.85 + rally ≥ 0.30, or
  // stop > 15 % away). UI must render a dedicated verdict, not the
  // generic 관망 fallback.
  it("renders 추세 유효 · 자리 지남 when analyzer stamps stretch_reason (RKLB-style)", () => {
    const r = makeResult({
      ticker: "RKLB",
      action: "HOLD",
      last_close: 124.77,
      stretch_reason: "8주 +115% (책 +50% 룰 위반) · 240MA 대비 +250%",
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 124.77, ma_10: 86.86,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: 35.66, above_ma_240: true,
          alignment_score: 0.6, overall_score: 0.88, label: "강세",
        },
        monthly: {
          timeframe: "monthly", price: 124.77, ma_10: 75,
          above_ma_10: true, ma_10_slope_up: true,
          ma_240: null, above_ma_240: null,
          alignment_score: 0.5, overall_score: 1.0, label: "강세",
        },
        book_signal: "BUY", book_reason: "정배열 + 추세 살아있음",
      },
      patterns: [],
      entry_plan: null,
    });
    render(<BookVerdict result={r} />);
    // Title chip "추세 유효 · 자리 지남" — appears in <h2>
    expect(screen.getByRole("heading", { name: /자리 지남/ })).toBeInTheDocument();
    // First body line carries the verbatim stretch_reason
    expect(screen.getByText(/8주 \+115%.*240MA 대비 \+250%/)).toBeInTheDocument();
    // Second line is the 240MA-distance narrative line (>50 % path)
    expect(screen.getByText(/주봉 240MA.*벗어남/)).toBeInTheDocument();
    // Holder-trailing-stop guidance
    expect(screen.getByText(/주봉 10MA.*86\.86.*이탈/)).toBeInTheDocument();
    // Friday next-decision line
    expect(screen.getByText(/다음 결정 시점.*금요일/)).toBeInTheDocument();
    // Must NOT render the generic catalyst-narrative 관망 verdict
    expect(screen.queryByText(/한 줄 평.*관망/)).toBeNull();
  });

  it("stretch verdict does not fire when stretch_reason is null (normal HOLD)", () => {
    const r = makeResult({
      action: "HOLD",
      last_close: 80,
      stretch_reason: null,
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
    // Normal HOLD path — generic 관망 card with 240MA narrative
    expect(screen.getByText(/한 줄 평.*관망/)).toBeInTheDocument();
    expect(screen.queryByText(/자리 지남/)).toBeNull();
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

/**
 * 088350.KS 2026-05-20 사용자 reported case:
 *   - 매복 verdict ("포킹 발사 4,944원 위로 매복")
 *   - analyze_results.last_close (지난주 금요일) = 4944
 *   - bars latest close (오늘) = 5300 — 이미 트리거 위
 *   사용자가 "이미 넘었는데 왜 대기?" 라는 인지 불일치 → 분석 시점 chip
 *   + trigger-cleared note 로 명시.
 */
describe("BookVerdict — currentPrice (analysis-vs-now) header chip + trigger-cleared note", () => {
  it("renders the analyzed-at header chip with fresh price + delta when currentPrice diverges", () => {
    const r = makeResult({
      ticker: "088350.KS",
      as_of: "2026-05-16",
      last_close: 4944,
      action: "STRONG_BUY",
      patterns: [
        {
          kind: "MA 수렴 매복", direction: "neutral", confidence: 0.55,
          completed: false, detected_at: "2026-05-16",
          entry: 4944, stop: 4500, target: null, reason: "",
          timeframe: "weekly", extra: {},
        },
      ],
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 4944, ma_10: 4944,
          above_ma_10: true, ma_10_slope_up: false,
          ma_240: 4200, above_ma_240: true,
          alignment_score: 0.4, overall_score: 0.75, label: "박스권",
        },
        monthly: null,
        book_signal: "BUY", book_reason: "",
      },
      volume_case: {
        case: 12, label_kr: "수렴기 거래량 감소",
        direction: "bullish", confidence: 0.65, reason: "",
      },
      last_candle: {
        date: "2026-05-16", open: 4900, high: 4960, low: 4870, close: 4944,
        volume: 100000, body_pct: 0.15, upper_wick_pct: 0.20, lower_wick_pct: 0.55,
        close_position: 0.40, is_bullish: true, tags: ["도지"], in_safe_zone_75: null,
      },
      consolidation_ratio: 0.04,
    });
    render(
      <BookVerdict
        result={r}
        currentPrice={5300}
        currentBarDate="2026-05-20"
      />,
    );
    // Header chip surfaces the analysis date + current price + delta
    expect(screen.getByText(/2026-05-16/)).toBeInTheDocument();
    // 4일 전 lives only in the chip (analysis-vs-now)
    expect(screen.getByText(/4일 전/)).toBeInTheDocument();
    // 매복 verdict still fires…
    expect(screen.getByText(/매복.*포킹 대기/)).toBeInTheDocument();
    // …and a trigger-cleared line is appended because currentPrice 5300
    // is above the ma_10w trigger 4944 (analyzed close was at the line).
    expect(
      screen.getByText(/분석 이후 현재가.*5,300.*포킹 트리거.*4,944/),
    ).toBeInTheDocument();
    expect(screen.getByText(/이번 주 발사 가능/)).toBeInTheDocument();
  });

  it("does NOT render the trigger-cleared note when current price has NOT crossed the trigger", () => {
    const r = makeResult({
      ticker: "088350.KS",
      as_of: "2026-05-16",
      last_close: 4500,    // analyzed below trigger
      action: "STRONG_BUY",
      patterns: [
        {
          kind: "MA 수렴 매복", direction: "neutral", confidence: 0.55,
          completed: false, detected_at: "2026-05-16",
          entry: 4500, stop: 4200, target: null, reason: "",
          timeframe: "weekly", extra: {},
        },
      ],
      trend: {
        daily: null,
        weekly: {
          timeframe: "weekly", price: 4500, ma_10: 4944,
          above_ma_10: false, ma_10_slope_up: false,
          ma_240: 4200, above_ma_240: true,
          alignment_score: 0.4, overall_score: 0.75, label: "박스권",
        },
        monthly: null,
        book_signal: "BUY", book_reason: "",
      },
      volume_case: {
        case: 12, label_kr: "수렴기 거래량 감소",
        direction: "bullish", confidence: 0.65, reason: "",
      },
      last_candle: {
        date: "2026-05-16", open: 4500, high: 4550, low: 4450, close: 4500,
        volume: 80000, body_pct: 0.15, upper_wick_pct: 0.20, lower_wick_pct: 0.55,
        close_position: 0.40, is_bullish: true, tags: ["도지"], in_safe_zone_75: null,
      },
      consolidation_ratio: 0.04,
    });
    // currentPrice 4700 still below ma_10w 4944 — no cleared note.
    render(
      <BookVerdict
        result={r}
        currentPrice={4700}
        currentBarDate="2026-05-20"
      />,
    );
    expect(screen.getByText(/매복.*포킹 대기/)).toBeInTheDocument();
    expect(screen.queryByText(/이번 주 발사 가능/)).toBeNull();
  });

  it("omits the analysis-vs-now chip when currentPrice is null (legacy callers)", () => {
    const r = makeResult({ ticker: "066620.KQ", as_of: "2026-05-22" });
    render(<BookVerdict result={r} />);
    // as_of date still renders, but no "현재" delta chip.
    expect(screen.queryByText(/현재 /)).toBeNull();
  });
});
