/**
 * paper_positions + paper_fills helpers (2026-05-27 reform).
 *
 * Broker-standard schema: one POSITION per (user, ticker) active at
 * a time, append-only FILL log for every buy/sell. The user-facing
 * /paper surface lists positions; expanding a position shows fills.
 *
 * Stats are computed at the FILL level for accuracy (each sell fill
 * is a realized event with its own pnl_pct + status_at_fill) while
 * the aggregate "current invested / current value" header is taken
 * from open positions.
 */
import { getServerClient } from "@/lib/supabase";
import { fetchLatestPrices, type LatestPrice } from "@/lib/latest-prices";


export type PositionStatus = "open" | "closed";
export type FillSide = "buy" | "sell";
export type FillStatusAtFill =
  | "closed_stop"
  | "closed_target"
  | "closed_manual";


export interface PaperPositionRow {
  id: string;
  user_id: string;
  ticker: string;
  status: PositionStatus;
  shares_open: number;
  total_invested_krw: number;
  realized_pnl_krw: number;
  initial_entry_price: number | null;
  initial_stop_loss: number | null;
  initial_target: number | null;
  notes: string | null;
  opened_at: string;
  closed_at: string | null;
  updated_at: string;
}


export interface PaperFillRow {
  id: string;
  position_id: string;
  user_id: string;
  side: FillSide;
  fill_date: string;
  fill_price: number;
  shares: number;
  amount_krw: number;
  stop_loss: number | null;
  target: number | null;
  pnl_krw: number | null;
  pnl_pct: number | null;
  status_at_fill: FillStatusAtFill | null;
  reason: string | null;
  alert_sent_at: string | null;
  created_at: string;
}


/** Position decorated with live market data + its fills. */
export interface PaperPositionLive extends PaperPositionRow {
  /** Fills, oldest → newest. */
  fills: PaperFillRow[];
  /** Current weekly close (null if no bar). */
  current_price: number | null;
  /** Weighted average cost of currently-open shares — null when
   *  position is closed (shares_open = 0). */
  avg_cost: number | null;
  /** Market value of currently-open shares at current_price. */
  current_value_krw: number | null;
  /** Unrealized P&L = current_value - cost_of_open_shares. null when
   *  closed (no shares left to revalue) OR no current_price. */
  unrealized_pnl_krw: number | null;
  unrealized_pnl_pct: number | null;
  /** Total realized + unrealized over the position's lifetime. */
  total_pnl_krw: number;
  total_return_pct: number;
  /** Convenience flags for UI chips on open positions. */
  stop_hit: boolean | undefined;
  target_hit: boolean | undefined;
}


export async function fetchOpenPositions(
  userId: string,
): Promise<PaperPositionLive[]> {
  return fetchPositions(userId, /* includeClosed */ false);
}


export async function fetchAllPositions(
  userId: string,
): Promise<PaperPositionLive[]> {
  return fetchPositions(userId, true);
}


export async function fetchOpenPositionForTicker(
  userId: string, ticker: string,
): Promise<PaperPositionRow | null> {
  const sb = getServerClient();
  const { data } = await sb
    .from("paper_positions")
    .select("*")
    .eq("user_id", userId)
    .eq("ticker", ticker)
    .eq("status", "open")
    .maybeSingle();
  return (data ?? null) as PaperPositionRow | null;
}


async function fetchPositions(
  userId: string, includeClosed: boolean,
): Promise<PaperPositionLive[]> {
  const sb = getServerClient();
  let q = sb.from("paper_positions").select("*")
    .eq("user_id", userId)
    .order("opened_at", { ascending: false });
  if (!includeClosed) q = q.eq("status", "open");
  const { data: positions, error } = await q.limit(500);
  if (error || !positions || positions.length === 0) return [];
  const ids = (positions as PaperPositionRow[]).map((p) => p.id);
  const { data: fillRows, error: fillErr } = await sb
    .from("paper_fills")
    .select("*")
    .in("position_id", ids)
    .order("fill_date", { ascending: true })
    .limit(2000);
  if (fillErr) {
    console.error("paper_fills read:", fillErr.message);
  }
  const fills = (fillRows ?? []) as PaperFillRow[];
  const byPosition = new Map<string, PaperFillRow[]>();
  for (const f of fills) {
    const arr = byPosition.get(f.position_id) ?? [];
    arr.push(f);
    byPosition.set(f.position_id, arr);
  }
  const tickers = Array.from(new Set((positions as PaperPositionRow[]).map((p) => p.ticker)));
  const prices: Map<string, LatestPrice> = tickers.length
    ? await fetchLatestPrices(tickers)
    : new Map();
  return (positions as PaperPositionRow[]).map((p) =>
    annotate(p, byPosition.get(p.id) ?? [], prices.get(p.ticker) ?? null),
  );
}


function annotate(
  p: PaperPositionRow,
  fills: PaperFillRow[],
  livePrice: LatestPrice | null,
): PaperPositionLive {
  const numP: PaperPositionRow = {
    ...p,
    shares_open: Number(p.shares_open),
    total_invested_krw: Number(p.total_invested_krw),
    realized_pnl_krw: Number(p.realized_pnl_krw),
    initial_entry_price: p.initial_entry_price != null ? Number(p.initial_entry_price) : null,
    initial_stop_loss: p.initial_stop_loss != null ? Number(p.initial_stop_loss) : null,
    initial_target: p.initial_target != null ? Number(p.initial_target) : null,
  };
  const numFills: PaperFillRow[] = fills.map((f) => ({
    ...f,
    fill_price: Number(f.fill_price),
    shares: Number(f.shares),
    amount_krw: Number(f.amount_krw),
    stop_loss: f.stop_loss != null ? Number(f.stop_loss) : null,
    target: f.target != null ? Number(f.target) : null,
    pnl_krw: f.pnl_krw != null ? Number(f.pnl_krw) : null,
    pnl_pct: f.pnl_pct != null ? Number(f.pnl_pct) : null,
  }));
  // avg_cost on currently-open shares — weighted by buy fills minus
  // shares already sold (FIFO/LIFO doesn't matter for the broker-style
  // weighted average; we treat all unsold shares as one bucket).
  let avgCost: number | null = null;
  if (numP.shares_open > 0) {
    let costRemaining = 0;
    let sharesRemaining = 0;
    for (const f of numFills) {
      if (f.side === "buy") {
        costRemaining += f.amount_krw;
        sharesRemaining += f.shares;
      } else {
        // Sell removes a proportional slice of remaining cost basis.
        if (sharesRemaining > 0) {
          const ratio = Math.min(1, f.shares / sharesRemaining);
          costRemaining -= costRemaining * ratio;
          sharesRemaining -= f.shares;
        }
      }
    }
    avgCost = sharesRemaining > 0 ? costRemaining / sharesRemaining : null;
  }
  const cp = livePrice?.close ?? null;
  const currentValue = (cp != null && numP.shares_open > 0)
    ? cp * numP.shares_open
    : null;
  let unrealizedKrw: number | null = null;
  let unrealizedPct: number | null = null;
  if (cp != null && avgCost != null && numP.shares_open > 0) {
    unrealizedKrw = (cp - avgCost) * numP.shares_open;
    unrealizedPct = (cp / avgCost - 1) * 100;
  }
  const totalPnl = numP.realized_pnl_krw + (unrealizedKrw ?? 0);
  const totalReturnPct = numP.total_invested_krw > 0
    ? (totalPnl / numP.total_invested_krw) * 100
    : 0;
  const stopHit = (cp != null && numP.initial_stop_loss != null)
    ? cp <= numP.initial_stop_loss : undefined;
  const targetHit = (cp != null && numP.initial_target != null)
    ? cp >= numP.initial_target : undefined;
  return {
    ...numP,
    fills: numFills,
    current_price: cp,
    avg_cost: avgCost,
    current_value_krw: currentValue,
    unrealized_pnl_krw: unrealizedKrw,
    unrealized_pnl_pct: unrealizedPct,
    total_pnl_krw: totalPnl,
    total_return_pct: totalReturnPct,
    stop_hit: stopHit,
    target_hit: targetHit,
  };
}


/** Aggregate stats — fill-level for accuracy, position-level for the
 *  header dashboard. */
export interface PaperStats {
  open_positions: number;
  closed_positions: number;
  total_invested_open_krw: number;     // open positions' cost basis
  total_current_value_krw: number;     // open positions' market value
  total_unrealized_pnl_krw: number;
  total_realized_pnl_krw: number;
  total_pnl_pct: number;               // (realized + unrealized) / invested
  // Fill-level closed-trade stats (sell fills)
  closed_fills: number;
  win_rate: number | null;
  avg_pnl_pct: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  payoff: number | null;
  best_pct: number | null;
  worst_pct: number | null;
  avg_hold_days: number | null;
}


export function computeStats(positions: PaperPositionLive[]): PaperStats {
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status !== "open");
  const total_invested_open = open.reduce(
    (s, p) => s + (p.avg_cost != null ? p.avg_cost * p.shares_open : 0), 0,
  );
  const total_current = open.reduce(
    (s, p) => s + (p.current_value_krw ?? (p.avg_cost != null
                    ? p.avg_cost * p.shares_open : 0)), 0,
  );
  const total_unrealized = open.reduce(
    (s, p) => s + (p.unrealized_pnl_krw ?? 0), 0,
  );
  const total_realized = positions.reduce(
    (s, p) => s + Number(p.realized_pnl_krw || 0), 0,
  );
  const totalInvested = positions.reduce(
    (s, p) => s + Number(p.total_invested_krw || 0), 0,
  );
  const totalPnlPct = totalInvested > 0
    ? ((total_realized + total_unrealized) / totalInvested) * 100
    : 0;
  // Fill-level stats — every sell fill is a closed event.
  const sellFills: PaperFillRow[] = [];
  for (const p of positions) for (const f of p.fills) {
    if (f.side === "sell" && f.pnl_pct != null) sellFills.push(f);
  }
  const pcts = sellFills.map((f) => Number(f.pnl_pct));
  const wins = pcts.filter((p) => p > 0);
  const losses = pcts.filter((p) => p < 0);
  const mean = (arr: number[]) => arr.length
    ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
  const avgWin = wins.length ? mean(wins) : null;
  const avgLoss = losses.length ? mean(losses) : null;
  const payoff = (avgWin != null && avgLoss != null && avgLoss !== 0)
    ? avgWin / Math.abs(avgLoss) : null;
  // hold_days — sell.fill_date minus the first buy on the same position.
  const holds: number[] = [];
  for (const p of positions) {
    const firstBuy = p.fills.find((f) => f.side === "buy");
    if (!firstBuy) continue;
    for (const f of p.fills) {
      if (f.side !== "sell") continue;
      const a = Date.parse(firstBuy.fill_date);
      const b = Date.parse(f.fill_date);
      if (Number.isFinite(a) && Number.isFinite(b))
        holds.push(Math.max(0, Math.round((b - a) / 86_400_000)));
    }
  }
  return {
    open_positions: open.length,
    closed_positions: closed.length,
    total_invested_open_krw: total_invested_open,
    total_current_value_krw: total_current,
    total_unrealized_pnl_krw: total_unrealized,
    total_realized_pnl_krw: total_realized,
    total_pnl_pct: totalPnlPct,
    closed_fills: sellFills.length,
    win_rate: pcts.length ? wins.length / pcts.length : null,
    avg_pnl_pct: pcts.length ? mean(pcts) : null,
    avg_win_pct: avgWin,
    avg_loss_pct: avgLoss,
    payoff,
    best_pct: pcts.length ? Math.max(...pcts) : null,
    worst_pct: pcts.length ? Math.min(...pcts) : null,
    avg_hold_days: holds.length ? Math.round(mean(holds)) : null,
  };
}


/** 17y backtest reference for the side-by-side comparison panel.
 *
 * Top-line CAGR/Sharpe/DD are from the 2026-05-27 L2 production run
 * (mid-cap sweet ranking — winner of the 14-variant grid). Trade-level
 * stats (win_rate / payoff / avg win / avg loss) are from the V0
 * book-only baseline since L2 changes the ranking, not the per-trade
 * exit logic — the distribution of individual trade outcomes is
 * essentially the same; only WHICH trades enter the top-50 differs. */
export const BACKTEST_REFERENCE = {
  cagr_pct: 20.65,
  sharpe: 0.83,
  win_rate: 0.45,
  avg_pnl_pct: 2.02,
  avg_win_pct: 12.85,
  avg_loss_pct: -6.86,
  payoff: 1.87,
} as const;
