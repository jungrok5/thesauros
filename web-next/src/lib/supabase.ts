/**
 * Supabase clients for the Thesauros site.
 *
 * Two flavors, picked per call site:
 *   - `getBrowserClient()` — uses NEXT_PUBLIC_SUPABASE_ANON_KEY. RLS-enforced.
 *     Safe for client components.
 *   - `getServerClient()`  — uses SUPABASE_SERVICE_KEY (RLS-bypassing).
 *     Only call from server components / route handlers. Pair with the
 *     authenticated user's email/id from `auth()` before reading per-user
 *     tables (watchlist / trade_log / alerts / alert_preferences).
 *
 * Note: we do NOT use Supabase Auth — sessions come from NextAuth (Google
 * OAuth + email allowlist). Per-user RLS would require minting a Supabase
 * JWT for each request; for now the server uses the service role and
 * filters by `users.email` derived from the NextAuth session.
 */
import { createClient, SupabaseClient } from "@supabase/supabase-js";

type Cfg = {
  url: string;
  serviceKey?: string;
  anonKey?: string;
};

function readEnv(): Cfg {
  const url =
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    process.env.SUPABASE_URL ??
    "";
  if (!url) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL (or SUPABASE_URL) is required");
  }
  return {
    url,
    serviceKey: process.env.SUPABASE_SERVICE_KEY,
    anonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  };
}

// Server-side: bypasses RLS. Never expose to the browser.
let _serverClient: SupabaseClient | null = null;
export function getServerClient(): SupabaseClient {
  if (_serverClient) return _serverClient;
  const cfg = readEnv();
  if (!cfg.serviceKey) {
    throw new Error("SUPABASE_SERVICE_KEY is required for server client");
  }
  _serverClient = createClient(cfg.url, cfg.serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return _serverClient;
}

// Browser-side: respects RLS. Safe to embed.
let _browserClient: SupabaseClient | null = null;
export function getBrowserClient(): SupabaseClient {
  if (_browserClient) return _browserClient;
  const cfg = readEnv();
  if (!cfg.anonKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is required");
  }
  _browserClient = createClient(cfg.url, cfg.anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return _browserClient;
}

// ---------- Shared row types (matches migrations/002_core_schema.sql) ------

export type Market = "KOSPI" | "KOSDAQ" | "NASDAQ" | "NYSE";

export interface TickerRow {
  ticker: string;
  name: string;
  market: Market;
  sector: string | null;
  industry: string | null;
  is_active: boolean;
}

export interface ScanResultRow {
  id: number;
  ticker: string;
  signal_type: string;
  timeframe: "daily" | "weekly" | "monthly";
  detected_at: string;            // ISO timestamp
  strength: number;
  reason: string | null;
  params: Record<string, unknown> | null;
  is_active: boolean;
}

export interface WatchlistRow {
  id: number;
  user_id: string;
  ticker: string;
  category: "observing" | "holding";
  entry_price: number | null;
  entry_date: string | null;
  note: string | null;
  alerts_enabled: boolean;
  created_at: string;
}

export interface MacroStateRow {
  id: 1;
  global_status: string | null;
  kr_status: string | null;
  indices: Record<string, string> | null;
  macro_indicators: Record<string, IndicatorStateRow> | null;
  mv_pq_signal: string | null;
  dial_scores: { liquidity: number; rate: number; cycle: number; price: number; fear: number } | null;
  one_line_guidance: string | null;
  updated_at: string;
}

export interface IndicatorStateRow {
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
}

export interface NewsRow {
  id: number;
  ticker: string | null;
  title: string;
  url: string;
  source: string | null;
  published_at: string | null;
  created_at: string;
}

export interface DisclosureRow {
  id: number;
  ticker: string | null;
  rcept_no: string;
  report_nm: string;
  report_type: string | null;
  filed_date: string | null;
  url: string | null;
  created_at: string;
}

export interface FinancialsEvalRow {
  ticker: string;
  revenue_3y: Record<string, number> | null;
  operating_income_3y: Record<string, number> | null;
  net_income_3y: Record<string, number> | null;
  assets_3y: Record<string, number> | null;
  debt_3y: Record<string, number> | null;
  equity_3y: Record<string, number> | null;
  debt_ratio: number | null;
  roe: number | null;
  roa: number | null;
  op_margin: number | null;
  revenue_growth_yoy: number | null;
  net_income_growth_yoy: number | null;
  current_ratio: number | null;
  f_score: number | null;
  rules_eval: Record<string, string> | null;
  composite_score: number | null;
  summary_text: string | null;
  updated_at: string;
}

export interface FactorsEvalRow {
  ticker: string;
  per: number | null; per_pctile: number | null; per_eval: string | null;
  pbr: number | null; pbr_pctile: number | null; pbr_eval: string | null;
  roe: number | null; roe_pctile: number | null; roe_eval: string | null;
  roa: number | null; roa_pctile: number | null; roa_eval: string | null;
  op_margin: number | null; op_margin_pctile: number | null; op_margin_eval: string | null;
  debt_ratio: number | null; debt_ratio_pctile: number | null; debt_ratio_eval: string | null;
  revenue_growth: number | null; revenue_growth_pctile: number | null;
  passes_kang_value: boolean | null;
  passes_graham: boolean | null;
  passes_magic_formula: boolean | null;
  passes_buffett: boolean | null;
  value_score: number | null;
  growth_score: number | null;
  safety_score: number | null;
  quality_score: number | null;
  summary_text: string | null;
  updated_at: string;
}

// ---------- Helpers: per-user data via NextAuth email --------------------

/**
 * Resolve (or create) the users row keyed by the NextAuth-provided email.
 * Returns the internal UUID used as `watchlist.user_id` etc.
 */
export async function ensureUserId(email: string, name: string | null = null): Promise<string> {
  const sb = getServerClient();
  // 1) try to read
  const { data: existing, error: readErr } = await sb
    .from("users")
    .select("id")
    .eq("email", email)
    .maybeSingle();
  if (readErr) throw readErr;
  if (existing?.id) return existing.id as string;
  // 2) insert
  const { data: inserted, error: insErr } = await sb
    .from("users")
    .insert({ email, name })
    .select("id")
    .single();
  if (insErr) throw insErr;
  return inserted.id as string;
}
