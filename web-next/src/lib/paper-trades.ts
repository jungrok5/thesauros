/**
 * paper_trades shared helpers — DB row shape + computed fields.
 *
 * Server-side fetchers + per-trade live P&L using the existing
 * latest-prices RPC. Used by /paper page, the per-ticker chip
 * shown on stock detail pages, and the buy modal validation.
 */
import { getServerClient } from "@/lib/supabase";
import { fetchLatestPrices, type LatestPrice } from "@/lib/latest-prices";

export type PaperStatus =
  | "open"
  | "closed_stop"
  | "closed_target"
  | "closed_manual";

export interface PaperTradeRow {
  id: string;
  user_id: string;
  ticker: string;
  entry_date: string;
  entry_price: number;
  amount_krw: number;
  shares: number;
  stop_loss: number | null;
  target: number | null;
  notes: string | null;
  status: PaperStatus;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  created_at: string;
}

export interface PaperTradeLive extends PaperTradeRow {
  /** Current market price (null when the ticker has no recent bar). */
  current_price: number | null;
  current_value_krw: number | null;
  pnl_krw: number | null;
  pnl_pct: number | null;
  /**
   * Stop-loss / target awareness so the UI can flag the row
   * — undefined if we can't compute (no current_price / no stop).
   */
  stop_hit: boolean | undefined;
  target_hit: boolean | undefined;
}


export async function fetchOpenTradesForUser(
  userId: string,
): Promise<PaperTradeLive[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("paper_trades")
    .select("*")
    .eq("user_id", userId)
    .eq("status", "open")
    .order("entry_date", { ascending: false });
  if (error || !data) return [];
  return annotateLive(data as PaperTradeRow[]);
}

export async function fetchAllTradesForUser(
  userId: string,
): Promise<PaperTradeLive[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("paper_trades")
    .select("*")
    .eq("user_id", userId)
    .order("entry_date", { ascending: false })
    .limit(500);
  if (error || !data) return [];
  return annotateLive(data as PaperTradeRow[]);
}

export async function fetchOpenForUserTicker(
  userId: string,
  ticker: string,
): Promise<PaperTradeRow[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("paper_trades")
    .select("*")
    .eq("user_id", userId)
    .eq("ticker", ticker)
    .eq("status", "open");
  if (error || !data) return [];
  return data as PaperTradeRow[];
}


/**
 * Decorate raw DB rows with live P&L. Closed rows use their
 * exit_price; open rows use the latest bar price (or null when
 * the bar is missing, which the UI surfaces as "가격 로드 중").
 */
async function annotateLive(rows: PaperTradeRow[]): Promise<PaperTradeLive[]> {
  const tickers = Array.from(new Set(rows.map((r) => r.ticker)));
  const prices: Map<string, LatestPrice> = tickers.length
    ? await fetchLatestPrices(tickers)
    : new Map();
  return rows.map((r) => {
    const livePrice: number | null = r.status === "open"
      ? prices.get(r.ticker)?.close ?? null
      : r.exit_price;
    let pnlKrw: number | null = null;
    let pnlPct: number | null = null;
    let currentValue: number | null = null;
    if (livePrice != null && Number.isFinite(livePrice)) {
      currentValue = livePrice * Number(r.shares);
      pnlKrw = currentValue - Number(r.amount_krw);
      pnlPct = (livePrice / Number(r.entry_price) - 1) * 100;
    }
    const stopHit = livePrice != null && r.stop_loss != null
      ? livePrice <= Number(r.stop_loss)
      : undefined;
    const targetHit = livePrice != null && r.target != null
      ? livePrice >= Number(r.target)
      : undefined;
    return {
      ...r,
      entry_price: Number(r.entry_price),
      amount_krw: Number(r.amount_krw),
      shares: Number(r.shares),
      stop_loss: r.stop_loss != null ? Number(r.stop_loss) : null,
      target: r.target != null ? Number(r.target) : null,
      exit_price: r.exit_price != null ? Number(r.exit_price) : null,
      current_price: livePrice,
      current_value_krw: currentValue,
      pnl_krw: pnlKrw,
      pnl_pct: pnlPct,
      stop_hit: stopHit,
      target_hit: targetHit,
    };
  });
}

/** Aggregate stats for the /paper header panel. */
export interface PaperStats {
  open_n: number;
  closed_n: number;
  total_invested_krw: number;
  total_current_value_krw: number;
  total_pnl_krw: number;
  total_pnl_pct: number;       // sum P&L / sum invested
  win_rate: number | null;     // closed trades only — null when no closes yet
  best_pct: number | null;
  worst_pct: number | null;
}

export function computeStats(rows: PaperTradeLive[]): PaperStats {
  const open = rows.filter((r) => r.status === "open");
  const closed = rows.filter((r) => r.status !== "open");
  const total_invested = open.reduce((s, r) => s + Number(r.amount_krw), 0);
  const total_current = open.reduce(
    (s, r) => s + (r.current_value_krw ?? Number(r.amount_krw)), 0,
  );
  const pnl = total_current - total_invested;
  const pnlPct = total_invested > 0 ? (pnl / total_invested) * 100 : 0;
  const closedWithPnl = closed
    .map((r) => r.pnl_pct)
    .filter((p): p is number => p != null && Number.isFinite(p));
  const wins = closedWithPnl.filter((p) => p > 0).length;
  return {
    open_n: open.length,
    closed_n: closed.length,
    total_invested_krw: total_invested,
    total_current_value_krw: total_current,
    total_pnl_krw: pnl,
    total_pnl_pct: pnlPct,
    win_rate: closedWithPnl.length
      ? wins / closedWithPnl.length
      : null,
    best_pct: closedWithPnl.length ? Math.max(...closedWithPnl) : null,
    worst_pct: closedWithPnl.length ? Math.min(...closedWithPnl) : null,
  };
}
