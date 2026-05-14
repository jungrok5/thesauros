/**
 * Typed client for the Thesauros FastAPI backend.
 *
 * Reads BACKEND_URL from env (server-only) or defaults to localhost:8000.
 * Pages should call these functions from server components or via Next.js
 * route handlers so the API URL never leaks to the client.
 */

const BACKEND_URL =
  process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const url = `${BACKEND_URL}${path}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend ${res.status}: ${url}`);
  }
  return (await res.json()) as T;
}

// ---------- types ----------
export type IndicatorState = {
  key: string;
  name_kr: string;
  category: string;
  book_ref: string;
  desc: string;
  value: number | null;
  as_of: string | null;
  yoy_pct: number | null;
  state: "BULL" | "NEUTRAL" | "CAUTION" | "BEAR";
  verdict: string;
  unit: string;
};

export type MacroRegime = {
  regime: string;
  score: number;
  n_indicators: number;
  vix_state: string | null;
  yield_curve_inverted: boolean;
  note: string;
  components: Array<{
    key: string;
    name_kr: string;
    state: string;
    verdict: string;
  }>;
};

export type MacroSnapshot = {
  regime: MacroRegime;
  indicators: Record<string, IndicatorState[]>;
};

export type MacroSeries = {
  key: string;
  name_kr: string;
  desc: string;
  book_ref: string;
  unit: string;
  category: string;
  series: Array<{ date: string; value: number }>;
  current_state: IndicatorState | null;
};

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

export type ScreenItem = {
  ticker: string;
  action: AnalysisResult["action"];
  book_score: number;
  last_close: number;
  as_of: string;
  trend_signal: string;
  trend_reason: string;
  n_patterns: number;
  top_pattern: string | null;
  top_pattern_confidence: number | null;
  top_pattern_timeframe: string | null;
  entry_plan: AnalysisResult["entry_plan"];
};

export type ScreenResponse = {
  market: string;
  min_score: number;
  total_scanned: number;
  n_candidates: number;
  items: ScreenItem[];
};

// ---------- API methods ----------
export const api = {
  health: () => get<{ ok: boolean; today: string }>("/api/health"),
  macroSnapshot: () => get<MacroSnapshot>("/api/macro"),
  macroRegime: () => get<MacroRegime>("/api/macro/regime"),
  macroSeries: (key: string, years = 5) =>
    get<MacroSeries>(`/api/macro/series/${key}?years=${years}`),
  analyze: (ticker: string, years = 5) =>
    get<AnalysisResult>(
      `/api/book/analyze?ticker=${encodeURIComponent(ticker)}&years=${years}`,
    ),
  screen: (
    market: "us" | "kr" | "all" = "all",
    minScore = 0.5,
    top = 50,
  ) =>
    get<ScreenResponse>(
      `/api/book/screen?market=${market}&min_score=${minScore}&top=${top}&require_completed=true`,
    ),
};

export type { ScreenItem as ScreenItemType };
