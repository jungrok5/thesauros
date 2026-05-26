/**
 * computeStats over the broker-standard schema (paper_positions
 * + paper_fills, 2026-05-27 reform).
 *
 * Position-level: open_positions / total_invested_open_krw /
 * total_current_value_krw / total_unrealized_pnl_krw /
 * total_realized_pnl_krw / total_pnl_pct.
 *
 * Fill-level: every SELL fill is one closed event — feeds win_rate
 * / avg_pnl_pct / payoff / avg_hold_days.
 */
import { describe, it, expect } from "vitest";
import {
  computeStats,
  type PaperPositionLive, type PaperFillRow,
} from "@/lib/paper-trades";


function fill(side: "buy" | "sell", overrides: Partial<PaperFillRow>): PaperFillRow {
  return {
    id: crypto.randomUUID(),
    position_id: "pos-1",
    user_id: "u1",
    side,
    fill_date: "2026-05-01",
    fill_price: 100,
    shares: 100,
    amount_krw: 10_000,
    stop_loss: 90,
    target: 120,
    pnl_krw: null,
    pnl_pct: null,
    status_at_fill: null,
    reason: null,
    alert_sent_at: null,
    created_at: "2026-05-01T00:00:00Z",
    ...overrides,
  };
}


function position(overrides: Partial<PaperPositionLive>): PaperPositionLive {
  const base: PaperPositionLive = {
    id: "pos-1",
    user_id: "u1",
    ticker: "TEST.KS",
    status: "open",
    shares_open: 100,
    total_invested_krw: 10_000,
    realized_pnl_krw: 0,
    initial_entry_price: 100,
    initial_stop_loss: 90,
    initial_target: 120,
    notes: null,
    opened_at: "2026-05-01T00:00:00Z",
    closed_at: null,
    updated_at: "2026-05-01T00:00:00Z",
    fills: [],
    current_price: 110,
    avg_cost: 100,
    current_value_krw: 11_000,
    unrealized_pnl_krw: 1_000,
    unrealized_pnl_pct: 10,
    total_pnl_krw: 1_000,
    total_return_pct: 10,
    stop_hit: false,
    target_hit: false,
  };
  return { ...base, ...overrides };
}


describe("computeStats — broker-standard paper positions", () => {
  it("empty list returns zeros + nullable stats null", () => {
    const s = computeStats([]);
    expect(s.open_positions).toBe(0);
    expect(s.closed_positions).toBe(0);
    expect(s.total_invested_open_krw).toBe(0);
    expect(s.total_pnl_pct).toBe(0);
    expect(s.win_rate).toBeNull();
    expect(s.payoff).toBeNull();
  });

  it("open position aggregates: invested + current value + unrealized P&L", () => {
    const s = computeStats([
      position({
        avg_cost: 100, shares_open: 100,
        current_value_krw: 11_000, unrealized_pnl_krw: 1_000,
        total_invested_krw: 10_000, realized_pnl_krw: 0,
      }),
      position({
        id: "pos-2", ticker: "B.KS",
        avg_cost: 200, shares_open: 50,
        current_value_krw: 9_500, unrealized_pnl_krw: -500,
        total_invested_krw: 10_000, realized_pnl_krw: 0,
      }),
    ]);
    expect(s.open_positions).toBe(2);
    expect(s.total_invested_open_krw).toBe(20_000);   // 100*100 + 200*50
    expect(s.total_current_value_krw).toBe(20_500);
    expect(s.total_unrealized_pnl_krw).toBe(500);
    expect(s.total_realized_pnl_krw).toBe(0);
    expect(s.total_pnl_pct).toBeCloseTo(2.5, 2);      // 500 / 20000
  });

  it("sell fills become closed events: win_rate / payoff", () => {
    // One position with 2 sell fills (분할 매도 → 추가 매도) of different P&L
    const s = computeStats([
      position({
        status: "closed",
        shares_open: 0,
        total_invested_krw: 10_000,
        realized_pnl_krw: 1_500,
        unrealized_pnl_krw: null,
        unrealized_pnl_pct: null,
        current_value_krw: null,
        avg_cost: null,
        total_pnl_krw: 1_500,
        total_return_pct: 15,
        fills: [
          fill("buy", { fill_date: "2026-05-01", fill_price: 100,
                        shares: 100, amount_krw: 10_000 }),
          fill("sell", { fill_date: "2026-05-15",
                         fill_price: 120, shares: 50, amount_krw: 6_000,
                         pnl_krw: 1_000, pnl_pct: 20,
                         status_at_fill: "closed_target",
                         reason: "분할 매도 (50%)" }),
          fill("sell", { fill_date: "2026-05-29",
                         fill_price: 110, shares: 50, amount_krw: 5_500,
                         pnl_krw: 500, pnl_pct: 10,
                         status_at_fill: "closed_manual",
                         reason: "수동 청산" }),
        ],
      }),
    ]);
    expect(s.closed_fills).toBe(2);
    expect(s.win_rate).toBe(1);                       // 2/2 winners
    expect(s.avg_pnl_pct).toBeCloseTo(15, 2);         // mean(20, 10)
    expect(s.best_pct).toBe(20);
    expect(s.worst_pct).toBe(10);
    expect(s.payoff).toBeNull();                       // no losers — defensive null
    expect(s.avg_hold_days).toBe(21);                  // mean of 14 + 28
  });

  it("mixed wins + losses: payoff = avg_win / |avg_loss|", () => {
    const s = computeStats([
      position({
        status: "closed", shares_open: 0,
        total_invested_krw: 10_000,
        realized_pnl_krw: 1_000,
        fills: [
          fill("buy",  { fill_date: "2026-04-01", fill_price: 100, shares: 100, amount_krw: 10_000 }),
          fill("sell", { fill_date: "2026-04-15", fill_price: 120,
                         shares: 50, amount_krw: 6_000,
                         pnl_krw: 1_000, pnl_pct: 20 }),
          fill("sell", { fill_date: "2026-04-29", fill_price:  95,
                         shares: 50, amount_krw: 4_750,
                         pnl_krw: -250, pnl_pct: -5 }),
        ],
      }),
    ]);
    expect(s.win_rate).toBeCloseTo(0.5, 5);
    expect(s.avg_win_pct).toBe(20);
    expect(s.avg_loss_pct).toBe(-5);
    expect(s.payoff).toBe(4);                          // 20 / 5
  });

  it("추매: position invested grows, fills both counted", () => {
    const s = computeStats([
      position({
        total_invested_krw: 30_000,            // first 10k + 추매 20k
        avg_cost: 100, shares_open: 300,
        current_value_krw: 33_000, unrealized_pnl_krw: 3_000,
        fills: [
          fill("buy", { fill_date: "2026-05-01", fill_price: 100,
                        shares: 100, amount_krw: 10_000 }),
          fill("buy", { fill_date: "2026-05-08", fill_price: 100,
                        shares: 200, amount_krw: 20_000,
                        reason: "추매" }),
        ],
      }),
    ]);
    expect(s.open_positions).toBe(1);
    expect(s.closed_fills).toBe(0);                    // no sells yet
    expect(s.total_invested_open_krw).toBe(30_000);
    expect(s.total_unrealized_pnl_krw).toBe(3_000);
  });
});
