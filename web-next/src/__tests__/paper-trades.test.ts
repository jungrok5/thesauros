/**
 * computeStats — pure aggregation, no DB. Pins the / paper page's
 * summary numbers so they stay correct when row shapes evolve.
 */
import { describe, it, expect } from "vitest";
import { computeStats, type PaperTradeLive } from "@/lib/paper-trades";

function row(overrides: Partial<PaperTradeLive>): PaperTradeLive {
  return {
    id: crypto.randomUUID(),
    user_id: "u1",
    ticker: "TEST.KS",
    entry_date: "2026-05-26",
    entry_price: 100,
    amount_krw: 1_000_000,
    shares: 10_000,
    stop_loss: 90,
    target: 120,
    notes: null,
    status: "open",
    exit_date: null,
    exit_price: null,
    exit_reason: null,
    created_at: "2026-05-26T00:00:00Z",
    current_price: 110,
    current_value_krw: 1_100_000,
    pnl_krw: 100_000,
    pnl_pct: 10,
    stop_hit: false,
    target_hit: false,
    ...overrides,
  };
}

describe("paper-trades computeStats", () => {
  it("returns zeros for an empty list", () => {
    const s = computeStats([]);
    expect(s.open_n).toBe(0);
    expect(s.closed_n).toBe(0);
    expect(s.total_invested_krw).toBe(0);
    expect(s.total_pnl_pct).toBe(0);
    expect(s.win_rate).toBeNull();
  });

  it("sums open positions and computes weighted P&L%", () => {
    const s = computeStats([
      row({ amount_krw: 1_000_000, current_value_krw: 1_100_000 }),  // +10%
      row({ amount_krw: 2_000_000, current_value_krw: 1_800_000 }),  // -10%
    ]);
    expect(s.open_n).toBe(2);
    expect(s.total_invested_krw).toBe(3_000_000);
    expect(s.total_current_value_krw).toBe(2_900_000);
    expect(s.total_pnl_krw).toBe(-100_000);
    expect(s.total_pnl_pct).toBeCloseTo(-3.333, 2);
  });

  it("computes win_rate from closed trades only", () => {
    const s = computeStats([
      row({ status: "open", pnl_pct: 5 }),    // open — ignored for win_rate
      row({ status: "closed_target", pnl_pct: 20 }),
      row({ status: "closed_stop", pnl_pct: -8 }),
      row({ status: "closed_target", pnl_pct: 12 }),
    ]);
    expect(s.closed_n).toBe(3);
    expect(s.win_rate).toBeCloseTo(2 / 3, 3);
    expect(s.best_pct).toBe(20);
    expect(s.worst_pct).toBe(-8);
  });

  it("falls back to amount when current_value is null (live price missing)", () => {
    const s = computeStats([
      row({ amount_krw: 1_000_000, current_value_krw: null,
            current_price: null, pnl_pct: null }),
    ]);
    // No live price → treat current = entry (don't surface fake P&L).
    expect(s.total_current_value_krw).toBe(1_000_000);
    expect(s.total_pnl_krw).toBe(0);
  });

  it("ignores open trades when computing best/worst", () => {
    const s = computeStats([
      row({ status: "open", pnl_pct: 50 }),
      row({ status: "closed_target", pnl_pct: 12 }),
      row({ status: "closed_stop", pnl_pct: -7 }),
    ]);
    expect(s.best_pct).toBe(12);  // not 50 (open)
    expect(s.worst_pct).toBe(-7);
  });
});
