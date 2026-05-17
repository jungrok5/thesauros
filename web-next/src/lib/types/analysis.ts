/**
 * Shape of an analyze_results row's `result` JSONB.
 * Produced by app.book.analyzer.analyze_ticker() (Python),
 * consumed by /stocks/[ticker] and AnalysisView.
 */

export type Pattern = {
  kind: string;
  direction: "bullish" | "bearish";
  confidence: number;
  completed: boolean;
  detected_at: string;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reason: string;
  timeframe?: "daily" | "weekly" | "monthly";
  extra?: Record<string, unknown>;
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
