/**
 * Shape of an analyze_results row's `result` JSONB.
 * Produced by app.book.analyzer.analyze_ticker() (Python),
 * consumed by /stocks/[ticker] and AnalysisView.
 */

export type Pattern = {
  kind: string;
  // "neutral" is emitted by setup-state detectors (e.g., MA 수렴 매복)
  // — a wait-and-watch pattern with no directional bet until the
  // trigger fires.
  direction: "bullish" | "bearish" | "neutral";
  confidence: number;
  completed: boolean;
  detected_at: string;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reason: string;
  timeframe?: "daily" | "weekly" | "monthly";
  extra?: Record<string, unknown>;
  /** Stamped true by the analyzer when price has moved past the book's
   *  invalidation level (쌍바닥 close < neckline, 쌍봉 close > N자
   *  탈출 수준, etc). Invalidated patterns no longer contribute to
   *  scoring or entry_plan, and BookVerdict surfaces them as
   *  "패턴 배신" warnings rather than buy signals. See
   *  app/book/analyzer.py:_mark_invalidated_patterns. */
  invalidated?: boolean;
  invalidation_reason?: string;
};

export type TrendSnapshot = {
  timeframe: string;
  price: number;
  ma_10: number;
  above_ma_10: boolean;
  ma_10_slope_up: boolean;
  ma_240: number | null;
  above_ma_240: boolean | null;
  alignment_score: number;
  overall_score: number;
  label: string;
} | null;

export type AnalysisResult = {
  ticker: string;
  as_of: string;
  last_close: number;
  rows: number;
  action: "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "SELL_OR_SHORT" | "AVOID";
  book_score: number;
  trend: {
    daily: TrendSnapshot;
    weekly: TrendSnapshot;
    monthly: TrendSnapshot;
    book_signal: string;
    book_reason: string;
  };
  last_candle: {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    body_pct: number;
    upper_wick_pct: number;
    lower_wick_pct: number;
    close_position: number;
    is_bullish: boolean;
    tags: string[];
    in_safe_zone_75: boolean | null;
  } | null;
  patterns: Pattern[];
  reversals: Pattern[];
  volume_case: {
    case: number;
    label_kr: string;
    direction: string;
    confidence: number;
    reason: string;
  } | null;
  /** (max(close) − min(close)) / last_close over the most recent
   *  ~4 bars. ≤ 0.06 means the chart is in a tight box (기간 조정 /
   *  빨래 널기); BookVerdict uses this as one of the 매복 signals. */
  consolidation_ratio?: number | null;
  /** Current price's position in the 52-week high-low range, 0..1.
   *  ≥0.85 = near recent high → post-rally / 반전 risk zone;
   *  combined with tight box + indecision candle, BookVerdict routes
   *  to "🟡 랠리 후 조정" instead of "🟡 매복" (semantically opposite). */
  position_in_52w?: number | null;
  /** Trailing 8-bar return as a fraction. 0.16 = +16 % over 8 weeks. */
  rally_8w_pct?: number | null;
  /** When the analyzer downgraded a BUY/STRONG_BUY to HOLD because the
   *  chart is in late-trend stretch territory (rally ≥ 50 %, 240MA
   *  distance > +100 %, 52w pos ≥ 0.85 + rally ≥ 0.30, or stop wider
   *  than 15 %), this carries the human-readable reason for the
   *  BookVerdict 추세 유효 · 자리 지남 branch. */
  stretch_reason?: string | null;
  reverse_accumulation: {
    detected: boolean;
    occurrences: number;
    first_idx: number;
    last_idx: number;
    floor: number;
    reason: string;
  } | null;
  entry_plan: {
    entry: number | null;
    stop: number | null;
    target: number | null;
    based_on: string;
  } | null;
};
